"""FUSION ADDITION: Delsys readers for the shared fusion get_data() contract."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from delsys_interface import DelsysInterface
from input_delsys_optional import SimulatedDelsysSensor


class DelsysFusionHub:
    """Poll one shared DelsysInterface and fan out per-sensor fusion samples."""

    def __init__(
        self,
        delsys_interface: DelsysInterface,
        sensor_map: Dict[str, int],
        *,
        left_sensor: str = "flexor",
        right_sensor: str = "extensor",
        simulate: bool = False,
        queue_size: int = 1000,
        keep_duration: float = 1.0,
    ):
        self.delsys_interface = delsys_interface
        self.sensor_map = dict(sensor_map)
        self.left_sensor = left_sensor
        self.right_sensor = right_sensor
        self.simulate = bool(simulate or delsys_interface.simulation_mode)
        self.queue_size = queue_size
        self.keep_duration = keep_duration
        self._lock = threading.Lock()
        self._buffers: Dict[str, deque] = {
            name: deque(maxlen=queue_size) for name in self.sensor_map
        }
        self._sim_sensors: Dict[str, SimulatedDelsysSensor] = {}
        self._running = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self.initialized = False
        if self.simulate:
            for name in self.sensor_map:
                self._sim_sensors[name] = SimulatedDelsysSensor(
                    name,
                    queue_size=queue_size,
                    keep_duration=keep_duration,
                )
        self.initialized = True

    def start(self) -> None:
        if self.simulate:
            self._running.set()
            self._poll_thread = threading.Thread(
                target=self._simulate_loop,
                name="delsys-fusion-sim",
                daemon=True,
            )
            self._poll_thread.start()
            return
        self._running.set()
        self._poll_thread = threading.Thread(
            target=self._hardware_poll_loop,
            name="delsys-fusion-hw",
            daemon=True,
        )
        self._poll_thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)

    def close(self) -> None:
        self.stop()

    def sensor_reader(self, sensor_name: str) -> "DelsysFusionSensor":
        return DelsysFusionSensor(self, sensor_name)

    def _simulate_loop(self) -> None:
        while self._running.is_set():
            now = time.perf_counter()
            for sensor in self._sim_sensors.values():
                sensor.append_simulated(now)
            time.sleep(0.001)

    def _hardware_poll_loop(self) -> None:
        while self._running.is_set():
            self._poll_hardware_once()
            time.sleep(0.0005)

    def _poll_hardware_once(self) -> None:
        if self.delsys_interface is None:
            return
        data = self.delsys_interface.get_emg_data_with_timestamps()
        ts = time.perf_counter()
        left = float(data.get("left", 0.0))
        right = float(data.get("right", 0.0))
        acc = (
            float(data.get("acc1_x", 0.0)),
            float(data.get("acc1_y", 0.0)),
            float(data.get("acc1_z", 0.0)),
            float(data.get("acc2_x", 0.0)),
            float(data.get("acc2_y", 0.0)),
            float(data.get("acc2_z", 0.0)),
        )
        with self._lock:
            if self.left_sensor in self._buffers:
                self._buffers[self.left_sensor].append((ts, (left, *acc)))
            if self.right_sensor in self._buffers:
                self._buffers[self.right_sensor].append((ts, (right, *acc)))

    def drain_sensor(
        self,
        sensor_name: str,
    ) -> List[Tuple[float, Tuple[float, float, float, float, float, float, float]]]:
        if self.simulate:
            sensor = self._sim_sensors.get(sensor_name)
            return sensor.get_data() if sensor is not None else []
        with self._lock:
            buffer = self._buffers.get(sensor_name)
            if buffer is None or not buffer:
                return []
            current_time = time.perf_counter()
            new_items = []
            temp_items = []
            last_ts = getattr(self, f"_last_ts_{sensor_name}", float("-inf"))
            while buffer:
                item = buffer.popleft()
                ts, vals = item
                if ts > last_ts:
                    new_items.append(item)
                if current_time - ts <= self.keep_duration:
                    temp_items.append(item)
            for item in temp_items:
                buffer.append(item)
            if not new_items:
                return []
            setattr(self, f"_last_ts_{sensor_name}", float(new_items[-1][0]))
            return new_items


class DelsysFusionSensor:
    """Per-sensor adapter exposing get_data() for DataFusion."""

    def __init__(self, hub: DelsysFusionHub, sensor_name: str):
        self.hub = hub
        self.sensor_name = sensor_name

    def get_data(self) -> List[Tuple[float, Tuple[float, float, float, float, float, float, float]]]:
        return self.hub.drain_sensor(self.sensor_name)
