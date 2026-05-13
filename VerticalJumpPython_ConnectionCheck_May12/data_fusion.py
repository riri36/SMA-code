"""Synchronize multi-rate sensor streams onto a shared fusion timeline."""

from __future__ import annotations

import bisect
import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from input_delsys_optional import OptionalDelsysHub
from input_HapticBall_interface import HapticBallReader


class DataFusion:
  """Collect raw sensor samples and publish time-aligned fusion frames."""

  class _TimestampRing:
    def __init__(self, dim: int, window_s: float = 1.0, delay: float = 0.03):
      self.dim = dim
      self.window_s = window_s
      self.ts: deque = deque()
      self.vals: deque = deque()
      self.previous1 = np.zeros((1, dim), dtype=np.float64)
      self.previous2 = np.zeros((1, dim), dtype=np.float64)
      self.delay = delay

    def append_many(self, ts: np.ndarray, vals: np.ndarray) -> None:
      assert vals.ndim == 2 and vals.shape[1] == self.dim
      assert ts.ndim == 1 and ts.shape[0] == vals.shape[0]
      for sample_ts, sample_vals in zip(ts, vals):
        self.ts.append(float(sample_ts))
        self.vals.append(sample_vals.astype(np.float64, copy=False))
      if not self.ts:
        return
      cut = self.ts[-1] - self.window_s
      while self.ts and self.ts[0] < cut:
        self.ts.popleft()
        self.vals.popleft()

    def interpolate_at(self, tproc: float) -> Tuple[List[Tuple[float, np.ndarray]], List[Tuple[float, float, float]]]:
      t = tproc - self.delay
      if len(self.ts) < 2 or t < self.ts[0] or t > self.ts[-1]:
        estimated_value = (self.previous1 - self.previous2) + self.previous1
        ts_value = [(tproc, estimated_value)]
        if len(self.ts) == 0:
          tz_value = [(t, float("nan"), float("nan"))]
        elif len(self.ts) == 1:
          tz_value = [(t, self.ts[0], self.ts[0])]
        else:
          tz_value = [(t, self.ts[0], self.ts[-1])]
        return ts_value, tz_value
      index = bisect.bisect_right(self.ts, t)
      left = max(0, index - 1)
      right = min(index, len(self.ts) - 1)
      if right <= left:
        right = min(left + 1, len(self.ts) - 1)
        left = max(0, right - 1)
      t0, t1 = self.ts[left], self.ts[right]
      v0, v1 = self.vals[left], self.vals[right]
      if t1 == t0:
        value = np.asarray(v0).reshape(1, -1).copy()
      else:
        ratio = (t - t0) / (t1 - t0)
        value = (v0 + ratio * (v1 - v0)).reshape(1, -1)
      ts_value = [(tproc, value)]
      tz_value = [(t, t0, t1)]
      self.previous2 = self.previous1
      self.previous1 = value
      return ts_value, tz_value

  def __init__(
    self,
    sensors: Optional[List[str]] = None,
    user_id: int | str = 1,
    fusion_rate: float = 200.0,
    delay: float = 0.03,
    delsys_sensor_map: Optional[Dict[str, int]] = None,
    simulate_delsys: bool = True,
    simulate_ball: bool = True,
    ball_device_name: str = "HapticBall",
    ball_reader: Optional[HapticBallReader] = None,
    window_s: float = 1.0,
  ):
    self.sensors = sensors or ["flexor", "extensor"]
    self.user_id = user_id
    self.fusion_rate = fusion_rate
    self.window_s = window_s
    self.delay = delay
    self.stop_event = threading.Event()
    self._lock = threading.Lock()
    self._streambuffer: Dict[str, DataFusion._TimestampRing] = {}
    self._raw_records: Dict[str, List[Tuple[float, np.ndarray]]] = {}
    self._fused_records: Dict[str, List[Tuple[float, np.ndarray]]] = {}
    self._timezone_inter: Dict[str, List[Tuple[float, float, float]]] = {}
    self.readers: Dict[str, Any] = {}
    self.simulate_delsys = simulate_delsys
    self.simulate_ball = simulate_ball
    self.ball_device_name = ball_device_name
    self.ball_reader = ball_reader
    self._owns_ball_reader = ball_reader is None
    self.delsys_sensor_map = delsys_sensor_map or {"flexor": 14, "extensor": 10}
    self.delsys_hub: Optional[OptionalDelsysHub] = None
    self._data_callbacks: List[Callable[[Dict[str, Any]], None]] = []
    self._latest_frame: Optional[Dict[str, Any]] = None
    self._frame_lock = threading.Lock()
    self._frame_queue: queue.Queue = queue.Queue(maxsize=10)
    self._init_readers()
    self.collector_thread = threading.Thread(target=self._raw_collection_loop, name="fusion-raw", daemon=True)
    self.processor_thread = threading.Thread(target=self._fusion_frame_loop, name="fusion-frame", daemon=True)

  def _init_readers(self) -> None:
    emg_sensors = [name for name in self.sensors if name in self.delsys_sensor_map]
    if emg_sensors:
      self.delsys_hub = OptionalDelsysHub(self.delsys_sensor_map, simulate=self.simulate_delsys)
      while not self.delsys_hub.initialized:
        time.sleep(0.01)
      self.delsys_hub.start()
      time.sleep(0.2 if self.simulate_delsys else 1.0)
      for sensor_name, sensor in self.delsys_hub.sensor_objs.items():
        if sensor_name not in self.sensors:
          continue
        self.readers[sensor_name] = sensor
        self.register_sensor(sensor_name, dim=7)
    # FUSION ADDITION: register HapticBall force samples on the fusion bus.
    if "ball_force" in self.sensors:
      if self.ball_reader is None:
        self.ball_reader = HapticBallReader(
          name="ball_force",
          simulate=self.simulate_ball,
          device_name=self.ball_device_name,
        )
        self.ball_reader.start()
      self.readers["ball_force"] = self.ball_reader
      self.register_sensor("ball_force", dim=1)

  def register_sensor(self, sensor_name: str, dim: int) -> None:
    self._streambuffer[sensor_name] = self._TimestampRing(dim=dim, window_s=self.window_s, delay=self.delay)
    self._raw_records[sensor_name] = []
    self._fused_records[sensor_name] = []
    self._timezone_inter[sensor_name] = []

  def register_data_callback(self, callback_func: Callable[[Dict[str, Any]], None]) -> None:
    self._data_callbacks.append(callback_func)

  def _raw_collection_loop(self) -> None:
    while not self.stop_event.is_set():
      for name in list(self.sensors):
        reader = self.readers.get(name)
        if reader is None:
          continue
        try:
          new_data = reader.get_data()
        except Exception:
          continue
        if not new_data:
          continue
        self._streambuffer[name].append_many(
          ts=np.array([sample_ts for sample_ts, _ in new_data], dtype=np.float64),
          vals=np.vstack([sample_vals for _, sample_vals in new_data]),
        )
        self._raw_records[name].extend(new_data)
      time.sleep(0.001)

  def _fusion_frame_loop(self) -> None:
    lag_threshold = 0.005
    period = 1.0 / self.fusion_rate
    next_t = time.perf_counter()
    while not self.stop_event.is_set():
      t_now = time.perf_counter()
      if t_now < next_t:
        time.sleep(next_t - t_now)
      elif t_now - next_t > lag_threshold:
        next_t = t_now
      t_target = next_t
      next_t += period
      frame_data: Dict[str, Any] = {}
      latest_ts = None
      with self._lock:
        for name, ring in self._streambuffer.items():
          ts_value, tz_value = ring.interpolate_at(t_target)
          if ts_value is None:
            continue
          self._fused_records[name].extend(ts_value)
          self._timezone_inter[name].extend(tz_value)
          ts, vec = ts_value[0]
          frame_data[name] = vec
          if latest_ts is None or ts > latest_ts:
            latest_ts = ts
      if latest_ts is not None:
        frame_data["ts"] = latest_ts
        with self._frame_lock:
          self._latest_frame = frame_data.copy()
        try:
          self._frame_queue.put_nowait(frame_data.copy())
        except queue.Full:
          try:
            self._frame_queue.get_nowait()
            self._frame_queue.put_nowait(frame_data.copy())
          except queue.Empty:
            pass
        for callback in self._data_callbacks:
          try:
            callback(frame_data)
          except Exception as exc:
            print(f"Fusion callback error: {exc}")
      time.sleep(0.001)

  def get_latest_frame(self) -> Optional[Dict[str, Any]]:
    with self._frame_lock:
      return self._latest_frame.copy() if self._latest_frame is not None else None

  def get_frame_from_queue(self, timeout: Optional[float] = 0.0) -> Optional[Dict[str, Any]]:
    try:
      if timeout is None:
        return self._frame_queue.get()
      if timeout == 0:
        return self._frame_queue.get_nowait()
      return self._frame_queue.get(timeout=timeout)
    except queue.Empty:
      return None

  def start_fusion(self) -> None:
    self.stop_event.clear()
    self.collector_thread.start()
    self.processor_thread.start()

  def stop_fusion(self) -> None:
    self.stop_event.set()
    if self.delsys_hub is not None:
      try:
        if getattr(self.delsys_hub, "base", None) is not None:
          self.delsys_hub.base.TrigBase.Stop()
          self.delsys_hub.base.TrigBase.ResetPipeline()
      except Exception:
        pass
    if self.ball_reader is not None and self._owns_ball_reader and self.ball_reader in self.readers.values():
      try:
        self.ball_reader.stop()
      except Exception:
        pass
    if self.collector_thread.is_alive():
      self.collector_thread.join(timeout=2.0)
    if self.processor_thread.is_alive():
      self.processor_thread.join(timeout=2.0)
    time.sleep(0.1)
    if self.delsys_hub is not None:
      try:
        self.delsys_hub.stop()
        self.delsys_hub.close()
      except Exception:
        pass
