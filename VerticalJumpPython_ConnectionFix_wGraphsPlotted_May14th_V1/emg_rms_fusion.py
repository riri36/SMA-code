"""Rolling RMS calculators used by the fusion feature path."""

from __future__ import annotations

from collections import deque
from typing import Tuple

import numpy as np


class FusionRmsCalculator:
  """Maintain a rolling RMS value as fused EMG samples arrive."""

  def __init__(self, window_size: int = 100):
    self.window_size = window_size
    self.data_buffer = deque(maxlen=window_size)
    self.timestamp_buffer = deque(maxlen=window_size)
    self.current_rms = 0.0
    self.last_timestamp = None

  def update(self, emg_value: float, timestamp: float | None = None) -> float:
    self.data_buffer.append(emg_value)
    if timestamp is not None:
      self.timestamp_buffer.append(timestamp)
      self.last_timestamp = timestamp
    if self.data_buffer:
      data_array = np.array(self.data_buffer)
      self.current_rms = float(np.sqrt(np.mean(data_array**2)))
    return self.current_rms

  def get_current_rms(self) -> float:
    return self.current_rms

  def reset(self) -> None:
    self.data_buffer.clear()
    self.timestamp_buffer.clear()
    self.current_rms = 0.0
    self.last_timestamp = None


class DualFusionRmsCalculator:
  """Rolling RMS calculators for the left/right EMG channels."""

  def __init__(self, window_size: int = 100):
    self.left = FusionRmsCalculator(window_size)
    self.right = FusionRmsCalculator(window_size)

  def update(self, left_value: float, right_value: float, timestamp: float | None = None) -> Tuple[float, float]:
    left_rms = self.left.update(left_value, timestamp)
    right_rms = self.right.update(right_value, timestamp)
    return left_rms, right_rms

  def get_current_rms(self) -> Tuple[float, float]:
    return self.left.get_current_rms(), self.right.get_current_rms()

  def reset(self) -> None:
    self.left.reset()
    self.right.reset()
