"""TCP client for lab mock EMG + ball stream (no pygame dependency).

Connects to ``mock_emg_ball_server.py`` and exposes thread-safe ``latest_sample()``.
Also provides ``MockTcpForceReader`` for the game's ``get_data()`` contract.
"""

from __future__ import annotations

import json
import math
import os
import socket
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

_lock = threading.Lock()
_latest: Optional[Dict[str, Any]] = None
_client_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_host = "127.0.0.1"
_port = 8765


def _parse_line(line: bytes) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _normalize_sample(obj: Dict[str, Any]) -> Dict[str, Any]:
    t = float(obj.get("t", time.time()))
    emg_l = float(obj.get("emg_l", obj.get("emgL", 0.0)))
    emg_r = float(obj.get("emg_r", obj.get("emgR", 0.0)))
    force = float(obj.get("force", obj.get("f", 0.0)))
    return {"t": t, "emg_l": emg_l, "emg_r": emg_r, "force": force}


def _client_loop() -> None:
    global _latest
    backoff = 0.25
    while not _stop.is_set():
        try:
            s = socket.create_connection((_host, _port), timeout=2.0)
            s.settimeout(2.0)
            f = s.makefile("rwb", buffering=0)
            backoff = 0.25
            buf = b""
            while not _stop.is_set():
                try:
                    chunk = f.read(4096)
                except (socket.timeout, OSError):
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    parsed = _parse_line(line)
                    if parsed is None:
                        continue
                    sample = _normalize_sample(parsed)
                    with _lock:
                        _latest = sample
        except OSError:
            pass
        with _lock:
            _latest = None
        for _ in range(int(backoff / 0.05)):
            if _stop.is_set():
                return
            time.sleep(0.05)
        backoff = min(2.0, backoff * 1.5)


def ensure_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """Start background TCP reader (idempotent)."""
    global _host, _port, _client_thread
    if host is not None:
        _host = host
    if port is not None:
        _port = int(port)
    with _lock:
        if _client_thread is not None and _client_thread.is_alive():
            return
        _stop.clear()
        t = threading.Thread(target=_client_loop, name="mock-emg-ball-client", daemon=True)
        _client_thread = t
    t.start()


def shutdown_client() -> None:
    """Stop background reader (best-effort)."""
    global _client_thread, _latest
    _stop.set()
    if _client_thread is not None and _client_thread.is_alive():
        _client_thread.join(timeout=1.5)
    _client_thread = None
    with _lock:
        _latest = None


def latest_sample() -> Optional[Dict[str, Any]]:
    """Return the most recent decoded JSON object, or None if not connected."""
    with _lock:
        if _latest is None:
            return None
        return dict(_latest)


class MockTcpForceReader:
    """Minimal ``HapticBallReader``-shaped adapter fed from ``latest_sample()``."""

    def __init__(
        self,
        name: str = "ball_force",
        simulate: bool = False,
        device_name: str = "HapticBall",
        scan_timeout_s: float = 10.0,
        queue_size: int = 1000,
        keep_duration: float = 1.0,
    ):
        self.name = name
        self.simulate = False
        self.device_name = device_name
        self.scan_timeout_s = scan_timeout_s
        self.keep_duration = keep_duration
        self.last_error: Optional[str] = None
        self.hardware_connected = True
        self.console_monitoring_active = False
        self._stream_active = False
        self._latest: Deque[Tuple[float, Tuple[float]]] = deque(maxlen=queue_size)
        self._last_ts_returned = float("-inf")
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._feed: Optional[threading.Thread] = None
        self._t0 = time.perf_counter()

    def probe_hardware(self) -> bool:
        return True

    def produce_verify_sample(self) -> bool:
        s = latest_sample()
        if s is None:
            self._append_sample(time.perf_counter(), 0.12)
            return True
        self._append_sample(time.perf_counter(), float(s["force"]))
        return True

    def start(self, *, stream: bool = True) -> None:
        if self._feed and self._feed.is_alive():
            self._stream_active = stream
            return
        host = os.environ.get("VERTICAL_JUMP_MOCK_DEVICE_HOST", "127.0.0.1")
        port = int(os.environ.get("VERTICAL_JUMP_MOCK_DEVICE_PORT", "8765"))
        ensure_client(host, port)
        self._running.set()
        self._stream_active = stream
        self._feed = threading.Thread(target=self._feed_loop, name="mock-ball-feed", daemon=True)
        self._feed.start()

    def activate_streaming(self) -> None:
        if not self._running.is_set():
            self.start(stream=True)
            return
        self._stream_active = True

    def deactivate_streaming(self) -> None:
        self._stream_active = False

    def stop(self) -> None:
        self._running.clear()
        self._stream_active = False
        if self._feed and self._feed.is_alive():
            self._feed.join(timeout=1.0)

    def close(self) -> None:
        self.stop()

    def _feed_loop(self) -> None:
        period = 1.0 / 60.0
        while self._running.is_set():
            if self._stream_active:
                s = latest_sample()
                if s is not None:
                    self._append_sample(time.perf_counter(), float(s["force"]))
                else:
                    now = time.perf_counter() - self._t0
                    f = 0.08 + 0.5 * max(0.0, math.sin(now * 1.2)) ** 2
                    self._append_sample(time.perf_counter(), f)
            time.sleep(period)

    def _append_sample(self, device_ts: float, force: float) -> None:
        with self._lock:
            self._latest.append((device_ts, (float(force),)))

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
