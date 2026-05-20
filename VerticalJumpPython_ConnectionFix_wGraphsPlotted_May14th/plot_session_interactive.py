#!/usr/bin/env python3
"""
Open interactive matplotlib figures for a saved session directory.

Usage:
  python plot_session_interactive.py /path/to/session_dir
  python plot_session_interactive.py --latest 0101010101

Requires a GUI matplotlib backend (MacOSX on macOS, TkAgg/Qt elsewhere).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent


def _pick_interactive_backend() -> str | None:
    import matplotlib

    forced = (os.environ.get("MPLBACKEND") or "").strip()
    candidates: list[str] = []
    if forced:
        candidates.append(forced)
    if sys.platform == "darwin":
        candidates.extend(["MacOSX", "TkAgg", "Qt5Agg", "QtAgg"])
    else:
        candidates.extend(["TkAgg", "Qt5Agg", "QtAgg", "MacOSX"])

    seen: set[str] = set()
    ordered: list[str] = []
    for name in candidates:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)

    for name in ordered:
        try:
            matplotlib.use(name, force=True)
            import matplotlib.pyplot as _plt  # noqa: F401

            return name
        except Exception:
            continue
    return None


def _resolve_latest_session(user_id: str) -> Path:
    base = REPO_ROOT / "GameData" / user_id
    if not base.is_dir():
        print(f"No directory: {base}", file=sys.stderr)
        sys.exit(2)
    candidates = [
        p
        for p in base.iterdir()
        if p.is_dir() and (p / "session_summary.json").is_file()
    ]
    if not candidates:
        print(f"No completed sessions under {base}", file=sys.stderr)
        sys.exit(3)
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive session plots (matplotlib).")
    parser.add_argument(
        "session_dir",
        nargs="?",
        help="Path to a session folder (contains session_summary.json)",
    )
    parser.add_argument(
        "--latest",
        metavar="USER_ID",
        help="Plot latest session under GameData/<USER_ID>/",
    )
    args = parser.parse_args(argv)

    if bool(args.latest) == bool(args.session_dir):
        parser.error("Provide exactly one of: session_dir path OR --latest USER_ID")

    if args.latest:
        session_path = _resolve_latest_session(args.latest)
    else:
        session_path = Path(args.session_dir).expanduser().resolve()
        if not session_path.is_dir():
            print(f"Not a directory: {session_path}", file=sys.stderr)
            return 2
        if not (session_path / "session_summary.json").is_file():
            print(
                f"Missing session_summary.json under {session_path}",
                file=sys.stderr,
            )
            return 2

    backend = _pick_interactive_backend()
    if backend is None:
        print(
            "No interactive matplotlib backend available "
            "(install PyQt5 or tkinter; on macOS, MacOSX backend is used).",
            file=sys.stderr,
        )
        return 1

    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    import matplotlib.pyplot as plt
    from session_plotter import build_session_figures_for_plt

    figures = build_session_figures_for_plt(session_path, plt)
    if not figures:
        print("No figures produced.", file=sys.stderr)
        return 1
    plt.show(block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
