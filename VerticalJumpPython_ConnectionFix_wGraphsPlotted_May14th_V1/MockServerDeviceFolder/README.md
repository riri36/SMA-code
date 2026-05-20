# Mock EMG + HapticBall TCP harness

This folder provides a **local-only** TCP stream and a launcher so the pygame game can run with **“mock hardware connected”** UI labels (green **Hardware**) for lab demos—**without** Trigno AeroPy DLLs or BLE peripherals.

## Security

- `mock_emg_ball_server.py` defaults to binding **`127.0.0.1`** only (loopback). Do not expose this protocol on a routable interface; it has no authentication.
- The background client in `mock_client_bridge.py` connects to the host/port from environment variables (default `127.0.0.1:8765`).

## Requirements

- Python 3.x with the same dependencies as the main game (pygame, numpy, …).
- No pygame import is required to import `mock_client_bridge` alone.

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `VERTICAL_JUMP_MOCK_DEVICES` | *(unset)* | Set to `1` to enable mock TCP EMG + ball integration in `delsys_interface.py`, `ball_force_monitor.py`, and startup ball probe in `emg_jump_game.py`. |
| `VERTICAL_JUMP_MOCK_DEVICE_PORT` | `8765` | TCP port for server and client. |
| `VERTICAL_JUMP_MOCK_DEVICE_HOST` | `127.0.0.1` | TCP host. |

When unset, game behavior is **unchanged**.

## Run the mock server alone

From the **repository root** (`VerticalJumpPython/`):

```bash
cd /path/to/VerticalJumpPython
python MockServerDeviceFolder/mock_emg_ball_server.py --host 127.0.0.1 --port 8765
```

Each accepted client receives one JSON object per line at ~60 Hz, for example:

`{"t":1.2,"emg_l":0.31,"emg_r":0.27,"force":0.42}`

## Run the game with mock devices (recommended)

**You must either use the launcher below or export the variables in the same shell before starting Python.** Starting `python -m emg_jump_game` from an IDE/debugger without `VERTICAL_JUMP_MOCK_DEVICES=1` skips mock mode: the game will use real Trigno/BLE paths and the verify screen will not match this harness.

This starts the server in a **subprocess**, sets the environment variables (also on the launcher process before any game import), and runs `python -m emg_jump_game` with an explicit merged `env` for the child (including on Windows):

```bash
cd /path/to/VerticalJumpPython
python MockServerDeviceFolder/run_game_with_mock_devices.py
```

Optional custom port:

```bash
export VERTICAL_JUMP_MOCK_DEVICE_PORT=9000
python MockServerDeviceFolder/run_game_with_mock_devices.py
```

## Manual two-terminal workflow

Terminal A:

```bash
python MockServerDeviceFolder/mock_emg_ball_server.py
```

Terminal B:

```bash
export VERTICAL_JUMP_MOCK_DEVICES=1
export VERTICAL_JUMP_MOCK_DEVICE_PORT=8765
python -m emg_jump_game
```

## Limitations and honesty label

- **Not real Delsys**: there is no AeroPy / Trigno pipeline; EMG values are JSON fields interpreted as left/right envelopes.
- **Not real HapticBall BLE**: force comes from the same TCP stream via `MockTcpForceReader`, not Nordic/BLE firmware.
- **UI wording**: the verify screen labels EMG as **Mock TCP** when this harness is active; the ball path still shows **Hardware** when the TCP stream is verified (fusion uses the same “live path” flags as a real session).
- If the TCP server is down, EMG falls back to a mild local sine in `_get_mock_tcp_emg_with_timestamps()` and ball connect may time out until the server is available.

For full game flow and connection flags, see `GAME_FLOW_AND_CONNECTION.md`.
