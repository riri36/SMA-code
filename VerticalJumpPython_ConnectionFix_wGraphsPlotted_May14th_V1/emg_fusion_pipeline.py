"""Threaded EMG fusion pipeline for gameplay jump detection."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from config import FUSION_CONFIG, BALL_CONFIG, should_print_ball_simulated_force
from data_fusion import DataFusion
from emg_rms_fusion import DualFusionRmsCalculator, FusionRmsCalculator
from fusion_trigger import FusionTriggerState, apply_fusion_threshold, build_fusion_triggers, evaluate_fusion_trigger
from input_HapticBall_interface import HapticBallReader


class EMGFusionPipeline:
  """Raw collection, fusion frames, RMS features, and trigger evaluation."""

  def __init__(
    self,
    calibration_values: Dict[str, float],
    *,
    control_mode: str = "emg",
    simulate_delsys: Optional[bool] = None,
    simulate_ball: Optional[bool] = None,
    ball_reader: Optional[HapticBallReader] = None,
    on_jump: Optional[Callable[[Dict[str, Any]], None]] = None,
    passive_logging: bool = False,
    session_start_perf: Optional[float] = None,
    delsys_interface: Optional[Any] = None,
  ):
    self.calibration_values = dict(calibration_values)
    self.control_mode = control_mode
    self.on_jump = on_jump
    self.passive_logging = passive_logging
    self.session_start_perf = session_start_perf or time.perf_counter()
    self.simulate_delsys = (
      FUSION_CONFIG["simulate_delsys"] if simulate_delsys is None else simulate_delsys
    )
    self.simulate_ball = (
      FUSION_CONFIG["simulate_ball"] if simulate_ball is None else simulate_ball
    )
    self.master_hz = float(FUSION_CONFIG["master_hz"])
    self.delay_s = float(FUSION_CONFIG["delay_s"])
    self.window_s = float(FUSION_CONFIG.get("window_s", 1.0))
    self.sensors = list(FUSION_CONFIG["sensors"])
    self.delsys_sensor_map = dict(FUSION_CONFIG["delsys_sensor_map"])
    self.left_sensor = str(FUSION_CONFIG["left_sensor"])
    self.right_sensor = str(FUSION_CONFIG["right_sensor"])
    self.ball_sensor = str(FUSION_CONFIG["ball_sensor"])
    self.rms_window = int(FUSION_CONFIG["rms_window"])
    self.ball_rms_window = int(FUSION_CONFIG["ball_rms_window"])
    self._stop = threading.Event()
    self._trigger_thread: Optional[threading.Thread] = None
    self._latest_features: Dict[str, float] = {}
    self._feature_lock = threading.Lock()
    self._jump_pending = False
    self._jump_lock = threading.Lock()
    self.raw_data_buffer: List[Dict[str, Any]] = []
    self.processed_emg_buffer: List[Dict[str, Any]] = []
    self.ball_force_buffer: List[Dict[str, Any]] = []
    self.jump_events: List[Dict[str, Any]] = []
    self._emg_rms = DualFusionRmsCalculator(self.rms_window)
    # FUSION ADDITION: rolling RMS on fused ball scalar at master_hz.
    self._ball_rms = FusionRmsCalculator(self.ball_rms_window)
    # FUSION ADDITION: throttle fused simulated ball force console output.
    self._sim_force_fused_print_count = 0
    self._sim_force_fused_print_last: Optional[float] = None
    self._sim_force_fused_print_last_wall = 0.0
    self._monitoring_active = False
    self._triggers = self._build_triggers()
    self._active_trigger = self._select_active_trigger(self.control_mode)
    self.update_calibration(self.calibration_values)
    self.fusion_bus = DataFusion(
      sensors=self.sensors,
      fusion_rate=self.master_hz,
      delay=self.delay_s,
      window_s=self.window_s,
      delsys_sensor_map=self.delsys_sensor_map,
      simulate_delsys=self.simulate_delsys,
      simulate_ball=self.simulate_ball,
      ball_device_name=str(FUSION_CONFIG["ball_device_name"]),
      ball_reader=ball_reader,
      delsys_interface=delsys_interface,
      left_sensor=self.left_sensor,
      right_sensor=self.right_sensor,
    )
    # FUSION ADDITION: fused frames feed the RMS feature path.
    self.fusion_bus.register_data_callback(self._on_fused_frame)

  def _build_triggers(self) -> Dict[str, FusionTriggerState]:
    triggers: Dict[str, FusionTriggerState] = {}
    for mode, trigger_cfg in FUSION_CONFIG["jump_triggers"].items():
      cfg = dict(trigger_cfg)
      if mode == "emg":
        cfg["threshold"] = float(self.calibration_values.get("threshold", cfg["threshold"]))
      elif mode == "force":
        force_threshold = self.calibration_values.get("force_threshold")
        if force_threshold is not None:
          cfg["threshold"] = float(force_threshold)
        if not FUSION_CONFIG.get("ball_trigger_use_rms", True):
          cfg["source"] = "ball.force"
      triggers[mode] = build_fusion_triggers([cfg])[0]
    return triggers

  def _select_active_trigger(self, mode: str) -> Optional[FusionTriggerState]:
    if mode == "keyboard":
      return None
    return self._triggers.get(mode)

  def set_control_mode(self, mode: str) -> None:
    """Switch the fused feature that drives jump triggers."""
    self.control_mode = mode
    self._active_trigger = self._select_active_trigger(mode)

  def update_calibration(self, calibration_values: Dict[str, float]) -> None:
    self.calibration_values = dict(calibration_values)
    emg_trigger = self._triggers.get("emg")
    if emg_trigger is not None:
      apply_fusion_threshold(emg_trigger, float(self.calibration_values["threshold"]))
    force_trigger = self._triggers.get("force")
    force_threshold = self.calibration_values.get("force_threshold")
    if force_trigger is not None and force_threshold is not None:
      apply_fusion_threshold(force_trigger, float(force_threshold))

  def start(self) -> None:
    self._stop.clear()
    self._monitoring_active = True
    # FUSION ADDITION: activate ball streaming and console hooks for gameplay fusion.
    if self.fusion_bus.ball_reader is not None:
      self.fusion_bus.ball_reader.console_monitoring_active = True
      self.fusion_bus.ball_reader.activate_streaming()
    self.fusion_bus.start_fusion()
    if self.control_mode == "keyboard":
      return
    # FUSION ADDITION: trigger evaluation runs on its own thread.
    self._trigger_thread = threading.Thread(target=self._trigger_loop, name="fusion-trigger", daemon=True)
    self._trigger_thread.start()

  def stop(self) -> None:
    self._stop.set()
    self._monitoring_active = False
    if self.fusion_bus.ball_reader is not None:
      self.fusion_bus.ball_reader.console_monitoring_active = False
    if self._trigger_thread and self._trigger_thread.is_alive():
      self._trigger_thread.join(timeout=2.0)
    self.fusion_bus.stop_fusion()

  def _mvc_value(self, side: str) -> float:
    peak_key = f"mvc_{side}_peak"
    if peak_key in self.calibration_values:
      return float(self.calibration_values[peak_key])
    return float(self.calibration_values.get(f"mvc_{side}", 0.8))

  def _normalize(self, side: str, rms_value: float) -> float:
    baseline_key = f"baseline_{side}"
    baseline = float(self.calibration_values.get(baseline_key, 0.05))
    mvc = self._mvc_value(side)
    span = max(mvc - baseline, 1e-6)
    normalized = (rms_value - baseline) / span
    return max(0.0, min(1.0, normalized))

  def _on_fused_frame(self, frame: Dict[str, Any]) -> None:
    ts = float(frame.get("ts", time.perf_counter()))
    sample_ts = float(frame.get("sample_ts", ts))
    left_raw = float(frame[self.left_sensor].reshape(-1)[0]) if self.left_sensor in frame else 0.0
    right_raw = float(frame[self.right_sensor].reshape(-1)[0]) if self.right_sensor in frame else 0.0
    left_rms, right_rms = self._emg_rms.update(left_raw, right_raw, ts)
    left_proc = self._normalize("left", left_rms)
    right_proc = self._normalize("right", right_rms)
    features = {
      f"emg.rms.{self.left_sensor}": left_proc,
      f"emg.rms.{self.right_sensor}": right_proc,
    }
    if self.ball_sensor in frame:
      force_raw = float(frame[self.ball_sensor].reshape(-1)[0])
      features["ball.force"] = force_raw
      force_rms = self._ball_rms.update(force_raw, ts)
      features["ball.force.rms"] = force_rms
      # FUSION ADDITION: periodic fused simulated ball force summaries.
      self._maybe_print_simulated_fused_force(force_raw, force_rms)
      self.ball_force_buffer.append(
        {
          "timestamp": time.time(),
          "session_elapsed_s": ts - self.session_start_perf,
          "perf_counter": ts,
          "sample_perf_counter": sample_ts,
          "force_raw": force_raw,
          "force_rms": force_rms,
        }
      )
    with self._feature_lock:
      self._latest_features = features
    self.raw_data_buffer.append(
      {
        "timestamp": ts,
        "sample_timestamp": sample_ts,
        "left_raw": left_raw,
        "right_raw": right_raw,
      }
    )
    self.processed_emg_buffer.append(
      {
        "timestamp": ts,
        "sample_timestamp": sample_ts,
        "unityTimestamp": ts,
        "localTimestamp": ts,
        "emg1": left_raw,
        "emg2": right_raw,
        "rms1": left_rms,
        "rms2": right_rms,
        "left_processed": left_proc,
        "right_processed": right_proc,
      }
    )

  def _maybe_print_simulated_fused_force(self, force_raw: float, force_rms: float) -> None:
    if not should_print_ball_simulated_force(
      self.simulate_ball,
      monitoring_active=self._monitoring_active,
    ):
      return
    self._sim_force_fused_print_count += 1
    now = time.time()
    every_n = max(int(BALL_CONFIG.get("print_simulated_force_every_n", 20)), 1)
    min_delta = float(BALL_CONFIG.get("print_simulated_force_min_delta", 0.08))
    interval_s = float(BALL_CONFIG.get("print_simulated_force_interval_s", 1.0))
    changed = (
      self._sim_force_fused_print_last is None
      or abs(force_rms - self._sim_force_fused_print_last) >= min_delta
    )
    periodic = (
      self._sim_force_fused_print_count % every_n == 0
      or now - self._sim_force_fused_print_last_wall >= interval_s
    )
    if not (changed or periodic):
      return
    print(
      f"[HapticBall sim fused] raw={force_raw:.3f} rms={force_rms:.3f}"
    )
    self._sim_force_fused_print_last = force_rms
    self._sim_force_fused_print_last_wall = now

  def _trigger_loop(self) -> None:
    interval = 1.0 / max(self.master_hz, 1.0)
    while not self._stop.is_set():
      trigger = self._active_trigger
      if trigger is None:
        time.sleep(interval)
        continue
      with self._feature_lock:
        features = dict(self._latest_features)
      value = features.get(trigger.source)
      if value is not None and evaluate_fusion_trigger(trigger, value):
        self._emit_jump(trigger, value, features)
      time.sleep(interval)

  def _emit_jump(self, trigger: FusionTriggerState, value: float, features: Dict[str, float]) -> None:
    left_value = float(features.get(f"emg.rms.{self.left_sensor}", 0.0))
    right_value = float(features.get(f"emg.rms.{self.right_sensor}", 0.0))
    ts = time.perf_counter()
    event = {
      "timestamp": time.time(),
      "session_elapsed_s": ts - self.session_start_perf,
      "perf_counter": ts,
      "left_value": left_value,
      "right_value": right_value,
      "force_value": float(
        features.get("ball.force.rms", features.get("ball.force", value))
      ),
      "threshold": trigger.threshold,
      "trigger_id": trigger.trigger_id,
      "source": trigger.source,
      "simulated": self.simulate_ball if trigger.source.startswith("ball.force") else self.simulate_delsys,
    }
    self.jump_events.append(event)
    with self._jump_lock:
      self._jump_pending = True
    if self.on_jump:
      self.on_jump(event)
    if trigger.source.startswith("ball.force"):
      print(f"JUMP! force:{value:.3f}")
    else:
      print(f"JUMP! L:{left_value:.3f} R:{right_value:.3f}")

  def consume_jump(self) -> bool:
    with self._jump_lock:
      if self._jump_pending:
        self._jump_pending = False
        return True
    return False
