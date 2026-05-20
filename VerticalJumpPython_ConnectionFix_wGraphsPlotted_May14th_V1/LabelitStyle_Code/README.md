# LabelitStyle_Code

HaptiCare-style **runtime-only** pygame shell around the existing ``emg_jump_game.IntegratedEMGGame`` flow. **No legacy repository files are modified**; integration is a subclass swap performed in ``bootstrap.py`` before ``main()`` runs.

## Run

From the VerticalJumpPython repository root:

```bash
python -m LabelitStyle_Code
```

Equivalent: ``python -m LabelitStyle_Code`` imports this package, patches ``emg_jump_game.IntegratedEMGGame`` to ``LabelitIntegratedEMGGame``, then calls ``emg_jump_game.main()``.

## Verify

```bash
python -m compileall LabelitStyle_Code
python -c "import LabelitStyle_Code.bootstrap"
```

``apply_patches()`` / ``run()`` load ``emg_jump_game`` (pygame / numpy / hardware glue). On some headless hosts that import chain can abort; the lightweight import above only loads ``bootstrap`` without pulling pygame.

## What changes at runtime

- ``IntegratedEMGGame`` is replaced by ``LabelitIntegratedEMGGame`` (same module globals, same ``EMGGameController`` / ``GameState`` machine).
- ``draw`` uses **Sessions**-first bottom navigation labels and routes off-workflow tabs to ``LabelitStyle_Code/panels/*``.
- ``handle_events`` duplicates the legacy loop so **keyboard routing is unchanged**, adding only optional hit detection for the Graphs **STOP RECORDING** stub (no-op until a legacy API exists).

## Live vs stubbed data

| Area | Source |
| --- | --- |
| Calibration, gameplay, session save | Unchanged legacy logic |
| Sessions tab cards | Read-only scan of ``config.DATA_LOGGING['base_directory']`` (default ``GameData/``): ``session_summary.json``, ``calibration/calibration_results.json``, CSV row counts |
| Dashboard grip % | Live: ``fusion_pipeline._latest_features`` keys ``emg.rms.*`` via ``getattr`` when the pipeline exists; otherwise a weak fallback from calibration dict |
| Finger bars | **Synthetic** (no per-finger sensors in this repo); documented in code |
| Mode chips (Constant/Dynamic/Burst/Pulse) | **Visual only** |
| Battery | **Stub** |
| Graphs STOP RECORDING | **Stub** (prints to console); fusion buffers drive mini charts when gameplay has started |
| IMU / Settings | Placeholder cards |

## Limitations

- Requires a working pygame display (same as ``python emg_jump_game.py``).
- Private fusion attributes (``_latest_features``, ``_feature_lock``) are read with ``getattr``; if internals rename, dashboard/graphs degrade gracefully.
