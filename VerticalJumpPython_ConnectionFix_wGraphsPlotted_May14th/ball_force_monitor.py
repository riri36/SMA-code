"""Threaded HapticBall force monitor for connection and calibration feedback."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import BALL_CONFIG, CONNECTION_CONFIG, should_print_ball_simulated_force
from fusion_trigger import FusionTriggerState, build_fusion_triggers, evaluate_fusion_trigger
from input_HapticBall_interface import HapticBallReader


class BallForceMonitor:
    """Collect force samples for connection verification and calibration feedback."""

    def __init__(
        self,
        *,
        simulate: bool = False,
        on_calibration_squeeze: Optional[Callable[[Dict[str, Any]], None]] = None,
        session_start_perf: Optional[float] = None,
    ):
        self.simulate_requested = simulate
        self.on_calibration_squeeze = on_calibration_squeeze
        self.calibration_feedback_enabled = False
        self.session_start_perf = session_start_perf or time.perf_counter()
        self._mock_tcp_devices = os.environ.get("VERTICAL_JUMP_MOCK_DEVICES") == "1"
        if self._mock_tcp_devices:
            mock_dir = Path(__file__).resolve().parent / "MockServerDeviceFolder"
            if str(mock_dir) not in sys.path:
                sys.path.insert(0, str(mock_dir))
            import mock_client_bridge  # noqa: WPS433

            self.reader = mock_client_bridge.MockTcpForceReader(
                simulate=False,
                device_name=BALL_CONFIG["device_name"],
                scan_timeout_s=float(BALL_CONFIG["scan_timeout_s"]),
                queue_size=int(BALL_CONFIG["queue_size"]),
                keep_duration=float(BALL_CONFIG["keep_duration"]),
            )
        else:
            self.reader = HapticBallReader(
                simulate=simulate,
                device_name=BALL_CONFIG["device_name"],
                scan_timeout_s=float(BALL_CONFIG["scan_timeout_s"]),
                queue_size=int(BALL_CONFIG["queue_size"]),
                keep_duration=float(BALL_CONFIG["keep_duration"]),
            )
        self._stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        # FUSION ADDITION: gameplay fusion owns jump triggers outside calibration.
        self.fusion_owns_triggers = False
        self.passive_logging = False
        self.force_samples: List[Dict[str, Any]] = []
        self.calibration_squeeze_events: List[Dict[str, Any]] = []
        self._calibration_trigger = self._build_calibration_trigger()
        self.connection_status = "idle"
        self.using_simulation = simulate
        # FUSION ADDITION: throttle monitor-path simulated force console output.
        self._sim_force_print_count = 0
        self._sim_force_print_last: Optional[float] = None
        self._sim_force_print_last_wall = 0.0

    def _build_calibration_trigger(self) -> FusionTriggerState:
        trigger_cfg = {
            "id": "calibration_squeeze",
            "source": "ball.force",
            "threshold": float(BALL_CONFIG["calibration_feedback_threshold"]),
            "arm_above": float(BALL_CONFIG["calibration_feedback_arm_above"]),
            "disarm_below": float(BALL_CONFIG["calibration_feedback_disarm_below"]),
            "refractory_ms": float(BALL_CONFIG["calibration_feedback_refractory_ms"]),
        }
        return build_fusion_triggers([trigger_cfg])[0]

    def connect(self) -> bool:
        """Start BLE streaming and verify that samples arrive."""
        self._stop.clear()
        if self._mock_tcp_devices:
            # MockTcpForceReader only appends samples when stream=True; stream=False
            # leaves _feed_loop idle so verify would always time out.
            self.reader.start(stream=True)
            deadline = time.time() + float(BALL_CONFIG["connection_verify_timeout_s"])
            while time.time() < deadline:
                samples = self.reader.get_data()
                if samples:
                    self.connection_status = "connected"
                    self.using_simulation = False
                    return True
                time.sleep(0.05)
            self.connection_status = "failed"
            self.using_simulation = False
            return False
        if self.simulate_requested:
            self.reader.simulate = True
            self.reader.produce_verify_sample()
            self.connection_status = "simulated"
            self.using_simulation = True
            return True
        self.reader.start(stream=False)
        deadline = time.time() + float(BALL_CONFIG["connection_verify_timeout_s"])
        while time.time() < deadline:
            samples = self.reader.get_data()
            if samples:
                self.connection_status = "simulated" if self.reader.simulate else "connected"
                self.using_simulation = self.reader.simulate
                if self.reader.simulate:
                    self.reader.deactivate_streaming()
                return True
            time.sleep(0.05)
        if (
            not self.reader.simulate
            and CONNECTION_CONFIG.get("allow_ball_simulation", True)
        ):
            self.reader.stop()
            self.reader.simulate = True
            self.reader.produce_verify_sample()
            self.connection_status = "simulated"
            self.using_simulation = True
            return True
        self.connection_status = "failed"
        self.using_simulation = self.reader.simulate
        return False

    def start_monitoring(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop.clear()
        # FUSION ADDITION: activate streaming and console hooks only for calibration monitoring.
        self.reader.console_monitoring_active = True
        self.reader.activate_streaming()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="ball-force-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def set_calibration_feedback(
        self,
        enabled: bool,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """Enable squeeze feedback during calibration without gameplay jump events."""
        self.calibration_feedback_enabled = enabled
        if callback is not None:
            self.on_calibration_squeeze = callback
        if enabled:
            self._calibration_trigger = self._build_calibration_trigger()
        # FUSION ADDITION: gate simulated force console output with calibration monitoring.
        self.reader.console_monitoring_active = enabled

    def release_reader(self) -> HapticBallReader:
        """FUSION ADDITION: hand the live reader to the fusion bus without closing BLE."""
        self._stop.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        self._monitor_thread = None
        return self.reader

    def stop(self) -> None:
        self._stop.set()
        self.reader.console_monitoring_active = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        self.reader.close()
        self._monitor_thread = None

    def _monitor_loop(self) -> None:
        interval = 1.0 / max(float(BALL_CONFIG["poll_hz"]), 1.0)
        while not self._stop.is_set():
            for sample_ts, values in self.reader.get_data():
                force = float(values[0])
                self._record_sample(sample_ts, force)
                if self.calibration_feedback_enabled and self.on_calibration_squeeze:
                    if evaluate_fusion_trigger(self._calibration_trigger, force, now=sample_ts):
                        self._emit_calibration_squeeze(sample_ts, force)
            time.sleep(interval)

    def _record_sample(self, sample_ts: float, force: float) -> None:
        self.force_samples.append(
            {
                "timestamp": time.time(),
                "session_elapsed_s": sample_ts - self.session_start_perf,
                "perf_counter": sample_ts,
                "force_raw": force,
            }
        )
        # FUSION ADDITION: calibration/connection monitor summaries for simulated force.
        self._maybe_print_simulated_force(force)

    def _maybe_print_simulated_force(self, force: float) -> None:
        monitoring_active = (
            self.calibration_feedback_enabled
            and self._monitor_thread is not None
            and self._monitor_thread.is_alive()
        )
        if not should_print_ball_simulated_force(
            self.using_simulation,
            monitoring_active=monitoring_active,
        ):
            return
        self._sim_force_print_count += 1
        now = time.time()
        every_n = max(int(BALL_CONFIG.get("print_simulated_force_every_n", 20)), 1)
        min_delta = float(BALL_CONFIG.get("print_simulated_force_min_delta", 0.08))
        interval_s = float(BALL_CONFIG.get("print_simulated_force_interval_s", 1.0))
        changed = (
            self._sim_force_print_last is None
            or abs(force - self._sim_force_print_last) >= min_delta
        )
        periodic = (
            self._sim_force_print_count % every_n == 0
            or now - self._sim_force_print_last_wall >= interval_s
        )
        if not (changed or periodic):
            return
        print(f"[HapticBall sim monitor] force={force:.3f}")
        self._sim_force_print_last = force
        self._sim_force_print_last_wall = now

    def _emit_calibration_squeeze(self, sample_ts: float, force: float) -> None:
        event = {
            "timestamp": time.time(),
            "session_elapsed_s": sample_ts - self.session_start_perf,
            "perf_counter": sample_ts,
            "source": "calibration_squeeze",
            "force_value": force,
            "threshold": self._calibration_trigger.threshold,
            "simulated": self.using_simulation,
        }
        self.calibration_squeeze_events.append(event)
        if self.on_calibration_squeeze:
            self.on_calibration_squeeze(event)

    def latest_force(self) -> Optional[float]:
        samples = self.reader.get_data()
        if not samples:
            return None
        return float(samples[-1][1][0])
