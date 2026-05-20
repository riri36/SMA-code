"""
Read-only discovery of saved sessions under ``GameData/<user>/<timestamp>/``.

Mirrors the on-disk layout ``emg_jump_game.EMGGameController`` creates: optional
``session_summary.json``, ``gameplay/*.csv``, ``calibration/calibration_results.json``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SessionRecord:
    user_id: str
    session_id: str
    path: Path
    summary: dict[str, Any]
    jump_count_estimate: int
    has_gameplay_csv: bool


def _count_csv_rows(path: Path, max_rows: int = 5000) -> int:
    if not path.is_file():
        return 0
    try:
        with path.open("r", newline="") as f:
            reader = csv.reader(f)
            n = sum(1 for _ in reader)
        return max(0, n - 1)  # exclude header when present
    except OSError:
        return 0


def load_session_summary(session_dir: Path) -> dict[str, Any]:
    p = session_dir / "session_summary.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_sessions(base_dir: Path, *, limit: int = 40) -> list[SessionRecord]:
    """
    Return recent sessions (newest first) by directory mtime under ``base_dir``.
    """
    if not base_dir.is_dir():
        return []
    found: list[SessionRecord] = []
    for user_dir in base_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        for session_dir in user_dir.iterdir():
            if not session_dir.is_dir():
                continue
            # Heuristic: timestamp folder ``YYYYMMDD_HHMMSS`` or any child session
            summary = load_session_summary(session_dir)
            session_id = summary.get("session_id") or session_dir.name
            gameplay = session_dir / "gameplay"
            jump_csv = gameplay / "jump_events.csv"
            raw_csv = gameplay / "raw_emg_data.csv"
            has_csv = jump_csv.is_file() or raw_csv.is_file()
            if not summary and not has_csv and not (session_dir / "calibration").is_dir():
                continue
            jumps = int(summary.get("total_jumps", 0) or 0)
            if jumps == 0 and jump_csv.is_file():
                jumps = min(_count_csv_rows(jump_csv), 999999)
            try:
                mtime = session_dir.stat().st_mtime
            except OSError:
                mtime = 0.0
            found.append(
                SessionRecord(
                    user_id=user_id,
                    session_id=str(session_id),
                    path=session_dir,
                    summary=summary,
                    jump_count_estimate=int(jumps),
                    has_gameplay_csv=has_csv,
                )
            )
    found.sort(key=lambda r: r.path.stat().st_mtime if r.path.exists() else 0, reverse=True)
    return found[:limit]


def load_calibration_peaks(session_dir: Path) -> dict[str, float]:
    p = session_dir / "calibration" / "calibration_results.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, float] = {}
    for key in (
        "mvc_left_peak",
        "mvc_right_peak",
        "mvc_left",
        "mvc_right",
        "mvc_force_peak",
        "baseline_force",
    ):
        v = data.get(key)
        if isinstance(v, (int, float)):
            out[key] = float(v)
    return out
