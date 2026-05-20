# Interactive session plots

After a session is saved under `GameData/<user_id>/<session_timestamp>/`, you can open **matplotlib** figures (EMG, optional ball force, jump markers) without re-running the game.

## One-liner (from repo root)

```bash
cd /path/to/VerticalJumpPython
python plot_session_interactive.py GameData/01010101/20260514_093602
```

## Latest session for a user

```bash
python plot_session_interactive.py --latest 01010101
```

Close all figure windows to exit the script (blocking GUI loop).

## Auto-spawn after save (optional)

In `config.py`, set:

```python
DATA_LOGGING['interactive_plot_on_session_end'] = True
```

The game then starts `plot_session_interactive.py` in a **detached subprocess** after CSV/JSON export.

Spawning is skipped when there is no usable desktop context, for example `CI=true`, or Linux without `DISPLAY`. `SDL_VIDEODRIVER=dummy` no longer blocks the spawn on **macOS** (matplotlib uses its own GUI stack). On Linux, dummy SDL still skips the spawn unless you set `DATA_LOGGING['interactive_plot_force'] = True` for local debugging (CI is never overridden).

Set `MPLBACKEND` before launch if needed, for example `MPLBACKEND=TkAgg` or on macOS `MPLBACKEND=MacOSX`. The subprocess also `setdefault`s a sensible backend.

```python
DATA_LOGGING['interactive_plot_force'] = True  # optional: Linux / SDL dummy desktop debugging only
```

Static PNG export from `auto_plot_session` is unchanged.
