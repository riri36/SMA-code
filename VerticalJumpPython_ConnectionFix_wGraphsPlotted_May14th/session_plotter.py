"""Generate session-end plots from saved gameplay and calibration data."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SOURCE_COLORS = {
    "emg": "#1f77b4",
    "force": "#ff7f0e",
    "keyboard": "#2ca02c",
}


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _time_origin(summary: Mapping[str, Any], config: Mapping[str, Any]) -> Optional[float]:
    origin = _safe_float(summary.get("gameplay_start_perf"))
    if origin is not None:
        return origin
    session = config.get("session", {})
    if isinstance(session, dict):
        return _safe_float(session.get("gameplay_start_perf"))
    return None


def _row_elapsed_s(row: Mapping[str, Any], time_origin: Optional[float]) -> Optional[float]:
    elapsed = _safe_float(row.get("session_elapsed_s"))
    if elapsed is not None:
        return elapsed
    perf = _safe_float(row.get("perf_counter"))
    if perf is not None and time_origin is not None:
        return perf - time_origin
    timestamp = _safe_float(row.get("timestamp"))
    if timestamp is not None and time_origin is not None:
        return timestamp - time_origin
    return timestamp


def _series_from_rows(
    rows: Sequence[Mapping[str, Any]],
    value_keys: Sequence[str],
    time_origin: Optional[float],
) -> Tuple[List[float], Dict[str, List[float]]]:
    times: List[float] = []
    series: Dict[str, List[float]] = {key: [] for key in value_keys}
    for row in rows:
        elapsed = _row_elapsed_s(row, time_origin)
        if elapsed is None:
            continue
        values = {key: _safe_float(row.get(key)) for key in value_keys}
        if all(value is None for value in values.values()):
            continue
        times.append(elapsed)
        for key, value in values.items():
            series[key].append(value if value is not None else float("nan"))
    return times, series


def _metadata_from_session(
    session_dir: Path,
    controller: Any = None,
) -> Dict[str, Any]:
    summary = _load_json(session_dir / "session_summary.json")
    config = _load_json(session_dir / "session_config.json")
    calibration = summary.get("calibration_values")
    if not isinstance(calibration, dict):
        calibration = config.get("calibration", {})
    if not isinstance(calibration, dict):
        calibration = {}

    metadata = {
        "user_id": summary.get("user_id") or getattr(controller, "user_id", ""),
        "session_id": summary.get("session_id") or getattr(controller, "session_id", ""),
        "control_mode": summary.get("control_mode") or getattr(controller, "control_mode", ""),
        "emg_simulated": None,
        "ball_simulated": None,
        "calibration": calibration,
        "mvc_threshold_percent": summary.get("mvc_threshold_percent"),
        "ball_force_threshold": summary.get("ball_force_threshold"),
        "time_origin": _time_origin(summary, config),
    }

    connections = summary.get("connections")
    if isinstance(connections, dict):
        metadata["emg_simulated"] = connections.get("emg_simulated")
        metadata["ball_simulated"] = connections.get("ball_simulated")
    else:
        metadata["emg_simulated"] = getattr(controller, "emg_using_simulation", None)
        metadata["ball_simulated"] = getattr(controller, "ball_using_simulation", None)

    if metadata["emg_simulated"] is None:
        metadata["emg_simulated"] = getattr(controller, "emg_using_simulation", None)
    if metadata["ball_simulated"] is None:
        metadata["ball_simulated"] = getattr(controller, "ball_using_simulation", None)
    if not metadata["control_mode"]:
        control = config.get("control", {})
        if isinstance(control, dict):
            metadata["control_mode"] = control.get("mode", "")
    if metadata["mvc_threshold_percent"] is None:
        metadata["mvc_threshold_percent"] = calibration.get("mvc_threshold_percent")
    if metadata["ball_force_threshold"] is None:
        ball = config.get("ball", {})
        if isinstance(ball, dict):
            ball_config = ball.get("config", {})
            if isinstance(ball_config, dict):
                metadata["ball_force_threshold"] = ball_config.get("force_threshold")
    return metadata


def _format_metadata_footer(metadata: Mapping[str, Any]) -> str:
    calibration = metadata.get("calibration", {})
    if not isinstance(calibration, dict):
        calibration = {}
    parts = [
        f"user={metadata.get('user_id', '')}",
        f"session={metadata.get('session_id', '')}",
        f"control={metadata.get('control_mode', '')}",
        f"emg={'sim' if metadata.get('emg_simulated') else 'hw'}",
        f"ball={'sim' if metadata.get('ball_simulated') else 'hw'}",
        (
            "baseline L/R="
            f"{calibration.get('baseline_left', 'n/a')}/"
            f"{calibration.get('baseline_right', 'n/a')}"
        ),
        (
            "MVC L/R="
            f"{calibration.get('mvc_left', calibration.get('mvc_left_peak', 'n/a'))}/"
            f"{calibration.get('mvc_right', calibration.get('mvc_right_peak', 'n/a'))}"
        ),
        f"threshold={calibration.get('threshold', 'n/a')}",
        f"MVC%={metadata.get('mvc_threshold_percent', calibration.get('mvc_threshold_percent', 'n/a'))}",
        f"ball_thr={metadata.get('ball_force_threshold', calibration.get('force_threshold', 'n/a'))}",
    ]
    return " | ".join(str(part) for part in parts)


def _annotate_jump_events(axis, events: Sequence[Mapping[str, Any]], time_origin: Optional[float]) -> None:
    for event in events:
        elapsed = _row_elapsed_s(event, time_origin)
        if elapsed is None:
            continue
        source = str(event.get("source") or "unknown").lower()
        color = SOURCE_COLORS.get(source, "#7f7f7f")
        axis.axvline(elapsed, color=color, alpha=0.45, linewidth=1.0, linestyle="--")
        axis.scatter([elapsed], [0.0], color=color, s=18, zorder=5)


def _plot_series(axis, times: Sequence[float], values: Sequence[float], *, label: str, color: str) -> None:
    if not times:
        return
    axis.plot(times, values, label=label, color=color, linewidth=1.0)


def _load_session_tables(
    session_dir: Path,
    controller: Any = None,
) -> Dict[str, List[Dict[str, Any]]]:
    tables = {
        "raw_emg": [],
        "processed_emg": [],
        "force_samples": [],
        "jump_events": [],
    }
    if controller is not None:
        tables["raw_emg"] = list(getattr(controller, "raw_data_buffer", []) or [])
        tables["processed_emg"] = list(getattr(controller, "processed_emg_buffer", []) or [])
        tables["force_samples"] = list(getattr(controller, "force_samples_buffer", []) or [])
        tables["jump_events"] = list(getattr(controller, "jump_events", []) or [])

    if not tables["raw_emg"]:
        tables["raw_emg"] = _read_csv_rows(session_dir / "gameplay" / "raw_emg_data.csv")
    if not tables["processed_emg"]:
        tables["processed_emg"] = _read_csv_rows(session_dir / "gameplay" / "processed_emg_data.csv")
    if not tables["force_samples"]:
        tables["force_samples"] = _read_csv_rows(session_dir / "gameplay" / "ball_force_samples.csv")
    if not tables["jump_events"]:
        tables["jump_events"] = _read_csv_rows(session_dir / "gameplay" / "jump_events.csv")
    return tables


def _has_plot_data(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    return any(bool(rows) for rows in tables.values())


def _save_figure(figure, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150, bbox_inches="tight")
    return output_path


def _plot_minimal_session(figure, metadata: Mapping[str, Any]) -> None:
    axis = figure.add_subplot(1, 1, 1)
    axis.axis("off")
    axis.text(
        0.5,
        0.55,
        "No session data recorded",
        ha="center",
        va="center",
        fontsize=14,
    )
    axis.text(
        0.5,
        0.35,
        _format_metadata_footer(metadata),
        ha="center",
        va="center",
        fontsize=9,
        wrap=True,
    )


def build_session_figures_for_plt(
    session_dir: Path | str,
    plt: Any,
    *,
    controller: Any = None,
) -> List[Any]:
    """Build matplotlib Figure objects using the caller's pyplot module (backend set by caller)."""
    session_path = Path(session_dir)
    if controller is not None and getattr(controller, "data_dir", None):
        session_path = Path(controller.data_dir)

    metadata = _metadata_from_session(session_path, controller)
    tables = _load_session_tables(session_path, controller)
    time_origin = metadata.get("time_origin")
    figures: List[Any] = []

    if not _has_plot_data(tables):
        figure = plt.figure(figsize=(10, 4))
        figure.suptitle(
            f"Session {metadata.get('session_id', '')} ({metadata.get('user_id', '')})",
            fontsize=12,
        )
        _plot_minimal_session(figure, metadata)
        figures.append(figure)
        return figures

    raw_times, raw_series = _series_from_rows(
        tables["raw_emg"],
        ("left_raw", "right_raw"),
        time_origin,
    )
    processed_times, processed_series = _series_from_rows(
        tables["processed_emg"],
        ("rms1", "rms2", "left_processed", "right_processed"),
        time_origin,
    )
    force_times, force_series = _series_from_rows(
        tables["force_samples"],
        ("force_raw", "force_rms"),
        time_origin,
    )

    overview = plt.figure(figsize=(12, 10))
    overview.suptitle(
        f"Session {metadata.get('session_id', '')} | user {metadata.get('user_id', '')}",
        fontsize=13,
    )

    axis_raw = overview.add_subplot(4, 1, 1)
    _plot_series(axis_raw, raw_times, raw_series["left_raw"], label="left_raw", color="#1f77b4")
    _plot_series(axis_raw, raw_times, raw_series["right_raw"], label="right_raw", color="#ff7f0e")
    axis_raw.set_ylabel("EMG raw")
    if raw_times:
        axis_raw.legend(loc="upper right", fontsize=8)
    axis_raw.grid(True, alpha=0.25)

    axis_proc = overview.add_subplot(4, 1, 2, sharex=axis_raw)
    _plot_series(axis_proc, processed_times, processed_series["rms1"], label="rms1", color="#1f77b4")
    _plot_series(axis_proc, processed_times, processed_series["rms2"], label="rms2", color="#ff7f0e")
    _plot_series(
        axis_proc,
        processed_times,
        processed_series["left_processed"],
        label="left_processed",
        color="#2ca02c",
    )
    _plot_series(
        axis_proc,
        processed_times,
        processed_series["right_processed"],
        label="right_processed",
        color="#d62728",
    )
    axis_proc.set_ylabel("EMG RMS / processed")
    if processed_times:
        axis_proc.legend(loc="upper right", fontsize=8, ncol=2)
    axis_proc.grid(True, alpha=0.25)

    axis_force = overview.add_subplot(4, 1, 3, sharex=axis_raw)
    if force_times:
        _plot_series(axis_force, force_times, force_series["force_raw"], label="force_raw", color="#9467bd")
        _plot_series(axis_force, force_times, force_series["force_rms"], label="force_rms", color="#8c564b")
        axis_force.legend(loc="upper right", fontsize=8)
    else:
        axis_force.text(
            0.5,
            0.5,
            "No ball force samples",
            ha="center",
            va="center",
            transform=axis_force.transAxes,
        )
    axis_force.set_ylabel("Ball force")
    axis_force.grid(True, alpha=0.25)

    axis_fused = overview.add_subplot(4, 1, 4, sharex=axis_raw)
    _plot_series(axis_fused, processed_times, processed_series["rms1"], label="rms1", color="#1f77b4")
    _plot_series(axis_fused, processed_times, processed_series["rms2"], label="rms2", color="#ff7f0e")
    if force_times:
        _plot_series(axis_fused, force_times, force_series["force_rms"], label="force_rms", color="#8c564b")
    _annotate_jump_events(axis_fused, tables["jump_events"], time_origin)
    axis_fused.set_ylabel("Fused view")
    axis_fused.set_xlabel("session_elapsed_s")
    if processed_times or force_times:
        axis_fused.legend(loc="upper right", fontsize=8)
    axis_fused.grid(True, alpha=0.25)

    overview.text(
        0.01,
        0.01,
        _format_metadata_footer(metadata),
        transform=overview.transFigure,
        fontsize=8,
        va="bottom",
    )
    figures.append(overview)

    jump_figure = plt.figure(figsize=(10, 2.8))
    jump_axis = jump_figure.add_subplot(1, 1, 1)
    jump_axis.set_title("Jump events by source")
    jump_axis.set_xlabel("session_elapsed_s")
    jump_axis.set_yticks([])
    _annotate_jump_events(jump_axis, tables["jump_events"], time_origin)
    for source, color in SOURCE_COLORS.items():
        jump_axis.scatter([], [], color=color, label=source)
    jump_axis.legend(loc="upper right", fontsize=8, ncol=3)
    jump_axis.grid(True, axis="x", alpha=0.25)
    figures.append(jump_figure)
    return figures


def _interactive_plot_skip_reason() -> Optional[str]:
    """If interactive session plots should not spawn, return a one-line reason; else None."""
    import os
    import sys

    try:
        from config import DATA_LOGGING
    except Exception:
        DATA_LOGGING = {}

    if DATA_LOGGING.get("interactive_plot_force"):
        if os.environ.get("CI", "").lower() in ("1", "true", "yes"):
            return "CI=true (interactive_plot_force does not override)"
        return None

    if os.environ.get("CI", "").lower() in ("1", "true", "yes"):
        return "CI=true"

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return "Linux without DISPLAY"

    # Pygame may use SDL dummy while matplotlib in a child still has a normal desktop; on macOS allow spawn.
    sdl = os.environ.get("SDL_VIDEODRIVER", "").lower()
    if sdl == "dummy" and not sys.platform.startswith("darwin"):
        return "SDL_VIDEODRIVER=dummy"

    return None


def session_interactive_plot_display_ok() -> bool:
    """Return False for typical headless environments (CI, Linux ssh without display)."""
    return _interactive_plot_skip_reason() is None


def spawn_interactive_session_plots(session_dir: Path | str) -> None:
    """Launch `plot_session_interactive.py` in a detached child (non-blocking; safe after pygame Agg)."""
    import os
    import subprocess
    import sys

    skip = _interactive_plot_skip_reason()
    if skip:
        print(f"Interactive session plots skipped: {skip}")
        return

    repo_root = Path(__file__).resolve().parent
    script = (repo_root / "plot_session_interactive.py").resolve()
    session_path = str(Path(session_dir).resolve())
    if not script.is_file():
        msg = f"Interactive session plots skipped: script missing ({script})"
        print(msg)
        logger.warning(msg)
        return

    cmd = [sys.executable, str(script), session_path]
    env = os.environ.copy()
    # Hint a GUI backend for the child; plot_session_interactive.py still picks a working one.
    if sys.platform == "darwin":
        env.setdefault("MPLBACKEND", "MacOSX")
    else:
        env.setdefault("MPLBACKEND", "TkAgg")

    popen_kw: Dict[str, Any] = {
        "cwd": str(repo_root),
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        creation = getattr(subprocess, "DETACHED_PROCESS", 0)
        creation |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creation:
            popen_kw["creationflags"] = creation
    else:
        popen_kw["start_new_session"] = True

    try:
        subprocess.Popen(cmd, **popen_kw)
        print("Interactive session plot viewer started (separate process; close figure windows to exit it).")
    except Exception:
        logger.exception("Interactive session plot subprocess failed for %s", session_path)
        print(f"Interactive session plots skipped: subprocess failed ({session_path})")


def auto_plot_session(
    session_dir: Path | str,
    *,
    controller: Any = None,
    output_subdir: str = "plots",
) -> List[Path]:
    """Plot and save session figures under the session directory."""
    session_path = Path(session_dir)
    if controller is not None and getattr(controller, "data_dir", None):
        session_path = Path(controller.data_dir)

    output_dir = session_path / output_subdir
    output_paths: List[Path] = []

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib is not installed; session auto-plot skipped")
        return []

    try:
        figures = build_session_figures_for_plt(session_path, plt, controller=controller)
        names = ["session_overview.png", "jump_events.png"]
        for index, figure in enumerate(figures):
            name = names[index] if index < len(names) else f"figure_{index}.png"
            output_paths.append(_save_figure(figure, output_dir / name))
            plt.close(figure)
    except Exception:
        logger.exception("Session auto-plot failed for %s", session_path)
        return output_paths

    return output_paths
