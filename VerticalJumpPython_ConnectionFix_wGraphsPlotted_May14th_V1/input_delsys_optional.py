from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple


class SimulatedDelsysSensor:
    def __init__(self, name: str, queue_size: int = 1000, keep_duration: float = 1.0):
        self.name = name
        self._latest = deque(maxlen=queue_size)
        self._last_ts_returned = float("-inf")
        self._lock = threading.Lock()
        self.keep_duration = keep_duration
        self._phase = random.random() * math.pi

    def get_data(self) -> List[Tuple[float, Tuple[float, float, float, float, float, float, float]]]:
        with self._lock:
            if not self._latest:
                return []
            current_time = time.perf_counter()
            new_items = []
            temp_items = []
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

    def append_simulated(self, ts: float) -> None:
        emg = 0.05 + 0.12 * abs(math.sin(ts * 2.0 + self._phase))
        if random.random() < 0.05:
            emg += random.uniform(0.2, 0.8)
        vals = (emg, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        with self._lock:
            self._latest.append((ts, vals))


class OptionalDelsysHub:
    """Wrap DelsysHub with simulation fallback for dry runs and smoke tests."""

    def __init__(self, sensor_map: Dict[str, int], simulate: bool = False):
        self.sensor_map = sensor_map
        self.simulate = simulate
        self.hardware_connected = False
        self.sensor_objs: Dict[str, object] = {}
        self.base = None
        self._sim_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self.initialized = False
        if simulate:
            self._init_simulated()
            return
        try:
            from input_Delsys_interface import DelsysHub

            self._hub = DelsysHub(sensor_map)
            self.sensor_objs = self._hub.sensor_objs
            self.base = self._hub.base
            self.hardware_connected = True
            self.initialized = True
        except Exception:
            self._init_simulated()

    def _init_simulated(self) -> None:
        self.simulate = True
        for name in self.sensor_map:
            self.sensor_objs[name] = SimulatedDelsysSensor(name)
        self.initialized = True

    def start(self) -> None:
        if self.simulate:
            self._running.set()
            self._sim_thread = threading.Thread(target=self._simulate_loop, daemon=True)
            self._sim_thread.start()
            return
        self._hub.start()

    def stop(self) -> None:
        if self.simulate:
            self._running.clear()
            if self._sim_thread and self._sim_thread.is_alive():
                self._sim_thread.join(timeout=1.0)
            return
        self._hub.stop()

    def close(self) -> None:
        if self.simulate:
            self.stop()
            return
        self._hub.close()

    def _simulate_loop(self) -> None:
        while self._running.is_set():
            now = time.perf_counter()
            for sensor in self.sensor_objs.values():
                sensor.append_simulated(now)
            time.sleep(0.001)
