# HaptiCare-style pygame shell

This project mirrors the **bottom navigation order and labels** from the Flutter app `hapticare_app` (`lib/haptic_app.dart`, `_buildMobileLayout`): **Insights → Graphs → Dashboard → Games → IMU → Settings**.

The pygame implementation is a **single-process** shell (`ui/hapticare_shell.py`, `ui/theme.py`) around the existing `IntegratedEMGGame` / `GameState` flow. Connection logic, `EMGGameController`, Delsys, HapticBall, and fusion gameplay are unchanged.

## Flutter tab → `GameState` / screen

| Tab (index) | Primary mapping | What you see |
| --- | --- | --- |
| **Insights** (0) | `SESSION_END` | Saving / session wrap-up (same legacy draw as before). |
| **Graphs** (1) | Placeholder | Reserved for trends / session plots (`session_plotter` when enabled in config). |
| **Dashboard** (2) | `INITIALIZATION`, `USER_INPUT`, `CONNECTION_VERIFY`, `USER_CHOICE`, `CALIBRATION`, `THRESHOLD_ADJUST`, `TRIGGER_MODE_SELECT` | Startup, user id, dual-path verify (E/C/R/ENTER), reuse vs recalibrate, calibration, MVC %, trigger mode. Same keyboard shortcuts as the legacy UI. |
| **Games** (3) | `MENU`, `PLAYING`, `GAME_OVER` | Main menu, flappy-style gameplay, game over. |
| **IMU** (4) | Placeholder | No IMU stack in this repo; tab holds layout parity only. |
| **Settings** (5) | Placeholder | Reserved for future tuning / config surface. |

On every **state change**, the active tab snaps to the workflow tab above so the visible tab matches the current step. You can still tap another tab to see a **Material-style placeholder card**; game logic and keyboard handlers keep running.

## Layout

- **Content area**: full window minus a **64px** bottom bar (same role as Flutter `bottomNavigationBar`).
- **Legacy screens** draw on a dark slate panel so existing light-colored labels remain readable inside the light outer chrome (`#F5F5F7`-style window background).
- **Gameplay** keeps the original sky-blue fill in the content region.

## Window resize (pygame 2 / SDL2)

The window is created with `pygame.RESIZABLE`. On resize:

- **SDL1 / older pygame**: `pygame.VIDEORESIZE` carries `w` / `h` (or `size`).
- **pygame 2 (e.g. 2.5+ / 2.6 with SDL2)**: you may also get `pygame.WINDOWRESIZED` and/or `pygame.WINDOWSIZECHANGED` with the new client size in `event.x` / `event.y`.

`IntegratedEMGGame` handles these, calls `pygame.display.set_mode` with the new size, then rebuilds `content_surface` via `_rebuild_layout_surfaces()` and repositions calibration feedback via `_layout_calibration_ui()`.

## Run

From this directory (same as before):

`python emg_jump_game.py` or `python -m emg_jump_game`

If the display cannot be opened (headless CI, sandbox), pygame will fail at `set_mode`; `python -m compileall` still validates syntax.
