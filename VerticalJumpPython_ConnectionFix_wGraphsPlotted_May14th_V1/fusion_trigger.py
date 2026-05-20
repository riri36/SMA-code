"""Hysteresis trigger state used by the fusion gameplay path."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class FusionTriggerState:
  trigger_id: str
  source: str
  threshold: float
  arm_above: float
  disarm_below: float
  refractory_s: float
  armed: bool = False
  last_fire_t: float = -1e9


def build_fusion_triggers(items: List[Dict[str, Any]]) -> List[FusionTriggerState]:
  triggers: List[FusionTriggerState] = []
  for item in items:
    threshold = float(item["threshold"])
    triggers.append(
      FusionTriggerState(
        trigger_id=str(item["id"]),
        source=str(item["source"]),
        threshold=threshold,
        arm_above=float(item.get("arm_above", threshold)),
        disarm_below=float(item.get("disarm_below", threshold * 0.55)),
        refractory_s=float(item.get("refractory_ms", 350)) / 1000.0,
      )
    )
  return triggers


def evaluate_fusion_trigger(
  trigger: FusionTriggerState,
  value: float,
  now: Optional[float] = None,
) -> bool:
  """Update trigger hysteresis and return True when a fire event should be emitted."""
  if not trigger.armed and value >= trigger.arm_above:
    trigger.armed = True
  elif trigger.armed and value <= trigger.disarm_below:
    trigger.armed = False
  if trigger.armed and value >= trigger.threshold:
    current = time.perf_counter() if now is None else now
    if current - trigger.last_fire_t >= trigger.refractory_s:
      trigger.last_fire_t = current
      return True
  return False


def apply_fusion_threshold(trigger: FusionTriggerState, threshold: float) -> None:
  trigger.threshold = threshold
  trigger.arm_above = threshold
  trigger.disarm_below = threshold * 0.55
  trigger.armed = False
