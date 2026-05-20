#!/usr/bin/env python3
"""Start mock TCP server subprocess, set env, launch ``python -m emg_jump_game``.

Environment variables for mock mode are applied at process start (before any
project imports). The game child process receives an explicit merged env dict
so ``VERTICAL_JUMP_MOCK_DEVICES`` and port/host are always set for ``emg_jump_game``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Lab harness env before any imports from the repo (this module only uses stdlib).
os.environ["VERTICAL_JUMP_MOCK_DEVICES"] = "1"
_port = int(os.environ.get("VERTICAL_JUMP_MOCK_DEVICE_PORT", "8765"))
os.environ["VERTICAL_JUMP_MOCK_DEVICE_PORT"] = str(_port)
_host = os.environ.get("VERTICAL_JUMP_MOCK_DEVICE_HOST", "127.0.0.1")
os.environ["VERTICAL_JUMP_MOCK_DEVICE_HOST"] = _host


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    server_script = Path(__file__).resolve().parent / "mock_emg_ball_server.py"
    port = int(os.environ.get("VERTICAL_JUMP_MOCK_DEVICE_PORT", "8765"))
    host = os.environ.get("VERTICAL_JUMP_MOCK_DEVICE_HOST", "127.0.0.1")

    proc_srv = subprocess.Popen(
        [sys.executable, str(server_script), "--host", host, "--port", str(port)],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.35)
    if proc_srv.poll() is not None:
        err = proc_srv.stderr.read().decode("utf-8", errors="replace") if proc_srv.stderr else ""
        print("Mock server failed to start:", err or "(no stderr)", file=sys.stderr)
        return 1

    env = {**os.environ, **{
        "VERTICAL_JUMP_MOCK_DEVICES": "1",
        "VERTICAL_JUMP_MOCK_DEVICE_PORT": str(port),
        "VERTICAL_JUMP_MOCK_DEVICE_HOST": host,
    }}

    try:
        return int(
            subprocess.run(
                [sys.executable, "-m", "emg_jump_game"],
                cwd=str(repo_root),
                env=env,
            ).returncode
        )
    finally:
        proc_srv.terminate()
        try:
            proc_srv.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc_srv.kill()


if __name__ == "__main__":
    raise SystemExit(main())
