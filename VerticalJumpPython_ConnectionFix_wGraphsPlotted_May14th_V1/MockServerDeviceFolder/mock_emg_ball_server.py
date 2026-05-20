#!/usr/bin/env python3
"""Local TCP server streaming synthetic EMG + force as JSON lines (~60 Hz).

Binds to loopback only (default ``127.0.0.1``) for lab use.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import threading
import time


def _stream_client(conn: socket.socket, hz: float) -> None:
    t0 = time.time()
    period = 1.0 / max(hz, 1.0)
    f = conn.makefile("wb", buffering=0)
    try:
        while True:
            t = time.time() - t0
            emg_l = 0.05 + 0.45 * abs(math.sin(t * 2.1))
            emg_r = 0.05 + 0.45 * abs(math.cos(t * 1.9))
            square = 0.35 if (int(t * 2) % 2 == 0) else 0.08
            emg_l += 0.15 * square
            force = 0.08 + 0.55 * max(0.0, math.sin(t * 0.9)) ** 3
            line = (
                json.dumps(
                    {"t": t, "emg_l": emg_l, "emg_r": emg_r, "force": force},
                    separators=(",", ":"),
                )
                + "\n"
            )
            f.write(line.encode("utf-8"))
            time.sleep(period)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description="Mock EMG + ball JSON-line TCP server")
    p.add_argument("--host", default="127.0.0.1", help="Bind address (127.0.0.1 loopback only)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--hz", type=float, default=60.0, help="Approximate line rate")
    args = p.parse_args()

    if args.host != "127.0.0.1":
        print("Only 127.0.0.1 is supported for --host (loopback lab use).", file=sys.stderr)
        return 2

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(4)
    print(f"mock_emg_ball_server listening on {args.host}:{args.port} at ~{args.hz} Hz")
    try:
        while True:
            conn, addr = srv.accept()
            print(f"client connected: {addr}")
            th = threading.Thread(
                target=_stream_client,
                args=(conn, float(args.hz)),
                daemon=True,
            )
            th.start()
    except KeyboardInterrupt:
        print("shutdown")
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
