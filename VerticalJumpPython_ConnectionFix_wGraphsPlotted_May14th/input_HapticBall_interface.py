"""BLE force reader for the HapticBall Arduino firmware.

Requires the `bleak` package for hardware BLE streaming.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import threading
import time
from collections import deque
from typing import Deque, List, Optional, Tuple

from config import BALL_CONFIG, should_print_ball_simulated_force

logger = logging.getLogger(__name__)

DEVICE_NAME = "HapticBall"
FSR_CHAR_UUID = "00002a56-0000-1000-8000-00805f9b34fb"
CMD_CHAR_UUID = "00002a57-0000-1000-8000-00805f9b34fb"


class HapticBallReader:
    """BLE force reader with the same get_data() shape as Delsys sensors."""

    def __init__(
        self,
        name: str = "ball_force",
        simulate: bool = False,
        device_name: str = DEVICE_NAME,
        scan_timeout_s: float = 10.0,
        queue_size: int = 1000,
        keep_duration: float = 1.0,
    ):
        self.name = name
        self.simulate = simulate
        self.device_name = device_name
        self.scan_timeout_s = scan_timeout_s
        self._latest: Deque[Tuple[float, Tuple[float]]] = deque(maxlen=queue_size)
        self._last_ts_returned = float("-inf")
        self._lock = threading.Lock()
        self.keep_duration = keep_duration
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ble_thread: Optional[threading.Thread] = None
        self._t0 = time.perf_counter()
        self.hardware_connected = False
        self.last_error: Optional[str] = None
        # FUSION ADDITION: keep simulated production quiet until a phase activates it.
        self._stream_active = False
        self.console_monitoring_active = False
        # FUSION ADDITION: throttle simulated force console output.
        self._sim_force_print_count = 0
        self._sim_force_print_last: Optional[float] = None
        self._sim_force_print_last_wall = 0.0

    def probe_hardware(self) -> bool:
        """FUSION ADDITION: scan for hardware without starting sample production."""
        try:
            return bool(asyncio.run(self._scan_for_device()))
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("HapticBall hardware probe failed: %s", exc)
            return False

    async def _scan_for_device(self) -> bool:
        from bleak import BleakScanner

        device = await BleakScanner.find_device_by_name(
            self.device_name,
            timeout=self.scan_timeout_s,
        )
        if device is None:
            self.last_error = f"Device '{self.device_name}' not found"
            return False
        return True

    def start(self, *, stream: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            self._stream_active = stream
            return
        self._running.set()
        self._stream_active = stream
        if self.simulate:
            self._thread = threading.Thread(target=self._simulate_loop, name="ball-sim", daemon=True)
        else:
            self._ble_thread = threading.Thread(target=self._ble_loop, name="ball-ble", daemon=True)
            self._ble_thread.start()
            deadline = time.time() + min(self.scan_timeout_s, 2.0)
            while time.time() < deadline and not self.hardware_connected and self._running.is_set():
                time.sleep(0.05)
            if not self.hardware_connected:
                self.last_error = f"Device '{self.device_name}' not found"
                logger.warning("HapticBall not found; falling back to simulation")
                self.simulate = True
            self._thread = threading.Thread(
                target=self._simulate_loop if self.simulate else self._noop_loop,
                name="ball-maint",
                daemon=True,
            )
        self._thread.start()

    def activate_streaming(self) -> None:
        """FUSION ADDITION: start continuous sample production for an active phase."""
        if not self._running.is_set():
            self.start(stream=True)
            return
        self._stream_active = True

    def deactivate_streaming(self) -> None:
        """FUSION ADDITION: pause sample production while keeping the worker alive."""
        self._stream_active = False

    def produce_verify_sample(self) -> bool:
        """FUSION ADDITION: emit one synthetic sample for passive connection checks."""
        if not self.simulate:
            return False
        now = time.perf_counter() - self._t0
        baseline = 0.08
        squeeze = max(0.0, math.sin(now * 0.7)) ** 3
        self._append_sample(time.perf_counter(), baseline + 0.9 * squeeze)
        return True

    def stop(self) -> None:
        self._running.clear()
        self._stream_active = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._ble_thread and self._ble_thread.is_alive():
            self._ble_thread.join(timeout=1.0)

    def close(self) -> None:
        self.stop()

    def get_data(self) -> List[Tuple[float, Tuple[float]]]:
        with self._lock:
            if not self._latest:
                return []
            current_time = time.perf_counter()
            new_items: List[Tuple[float, Tuple[float]]] = []
            temp_items: List[Tuple[float, Tuple[float]]] = []
            while self._latest:
                item = self._latest.popleft()
                ts, vals = item
                if ts > self._last_ts_returned:
                    new_items.append(item)
                if current_time - ts <= self.keep_duration:
                    temp_items.append(item)
            for item in temp_items:
                self._latest.append(item)
            if not new_items:
                return []
            self._last_ts_returned = float(new_items[-1][0])
            return new_items

    def _append_sample(self, device_ts: float, force: float) -> None:
        with self._lock:
            self._latest.append((device_ts, (float(force),)))
        # FUSION ADDITION: echo simulated raw force samples without spamming the console.
        self._maybe_print_simulated_force(float(force), source="raw")

    def _maybe_print_simulated_force(self, force: float, *, source: str = "raw") -> None:
        if not should_print_ball_simulated_force(
            self.simulate,
            monitoring_active=self.console_monitoring_active,
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
        print(f"[HapticBall sim {source}] force={force:.3f}")
        self._sim_force_print_last = force
        self._sim_force_print_last_wall = now

    def _simulate_loop(self) -> None:
        while self._running.is_set():
            if self._stream_active:
                now = time.perf_counter() - self._t0
                baseline = 0.08
                squeeze = max(0.0, math.sin(now * 0.7)) ** 3
                if random.random() < 0.03:
                    squeeze += random.uniform(0.2, 0.7)
                self._append_sample(time.perf_counter(), baseline + 0.9 * squeeze)
            time.sleep(0.05)

    def _noop_loop(self) -> None:
        while self._running.is_set():
            time.sleep(0.05)

    def _ble_loop(self) -> None:
        try:
            asyncio.run(self._connect_and_stream())
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("HapticBall BLE worker failed: %s", exc)
            self.hardware_connected = False
            self.simulate = True

    async def _connect_and_stream(self) -> None:
        from bleak import BleakClient, BleakScanner

        device = await BleakScanner.find_device_by_name(self.device_name, timeout=self.scan_timeout_s)
        if device is None:
            self.last_error = f"Device '{self.device_name}' not found"
            return
        async with BleakClient(device) as client:
            self.hardware_connected = True
            await client.write_gatt_char(CMD_CHAR_UUID, b"SYNC", response=True)

            def notification_handler(_sender, data: bytearray) -> None:
                try:
                    line = data.decode("utf-8", errors="strict").strip()
                except UnicodeDecodeError:
                    return
                parts = [part.strip() for part in line.split(",")]
                if len(parts) != 2:
                    return
                try:
                    float(parts[0])
                    force = float(parts[1])
                except ValueError:
                    return
                self._append_sample(time.perf_counter(), force)

            await client.start_notify(FSR_CHAR_UUID, notification_handler)
            while client.is_connected and self._running.is_set():
                await asyncio.sleep(0.05)
            try:
                await client.write_gatt_char(CMD_CHAR_UUID, b"SLEEP", response=True)
            except Exception:
                pass
            await client.stop_notify(FSR_CHAR_UUID)
        self.hardware_connected = False
