# GameData session files — field guide

This guide explains the JSON and CSV files the vertical jump game writes under each **session folder**. A session is one run of the app for a given user: everything from calibration through gameplay is stored together so you can replay, plot, or analyze it later.

## Where sessions live

- **Path pattern:** `GameData/<user_id>/<session_id>/`
- **`user_id`:** folder name for the person (for example `0101010101`).
- **`session_id`:** usually a timestamp string like `20260514_092156` (one folder per run). If someone plays more than once, pick the **newest** `session_id` folder (sort by name or modified time).

### Sample data used for this guide

For user `0101010101`, the most recent session folder found was **`20260514_092156`**. All example column names and JSON keys below match that run and the current game code. If your copy of `GameData/0101010101/` is empty or missing, the field meanings here still apply — they are defined by the Python save logic in `emg_jump_game.py`, `emg_fusion_pipeline.py`, and `ball_force_monitor.py`.

---

## `session_summary.json`

Written at the end of a session. High-level “report card” plus copies of important calibration numbers.

| Field | What it is | Why it matters |
|--------|--------------|----------------|
| `user_id` | Same as the parent folder name | Ties the file to the right player folder. |
| `session_id` | Same as the timestamp subfolder | Identifies this specific run. |
| `start_time` | Wall-clock time when the session began (seconds since Unix epoch) | Order sessions in real-world time. |
| `end_time` | Wall-clock time when the session ended | Same as above; with `start_time` gives session length. |
| `duration` | `end_time - start_time` in seconds | Quick sense of how long they were in the app. |
| `total_jumps` | Count of rows that were logged as jumps | Simple performance summary. |
| `control_mode` | How jumps were triggered this run (`emg`, `force`, or `keyboard`) | Explains which sensor path was “primary.” |
| `mvc_threshold_percent` | Percent setting used for the **EMG** jump threshold relative to their MVC range | Higher usually means they must squeeze harder to jump on EMG. |
| `connections` | Flags: EMG/ball verified, simulated vs hardware | Tells you whether numbers came from real devices or simulation. |
| `ball_simulated` | Whether the ball path used simulation | Same idea, surfaced again for convenience. |
| `gameplay_start_time` | Wall-clock time when gameplay logging started | Aligns CSV `timestamp` columns that use `time.time()` with “real life.” |
| `gameplay_start_perf` | `time.perf_counter()` when gameplay started | Anchor for aligning high-resolution timing with other streams (see FAQ). |
| `passive_emg_logging` | `true` when EMG was not the primary control mode but EMG may still be logged | Explains why EMG columns might exist even in force/keyboard mode. |
| `passive_ball_logging` | `true` when force was not primary but ball samples may still be logged | Same for force columns. |
| `fusion_master_hz` | Target rate of the fusion processing loop | How often per second fused features were updated (nominal). |
| `fusion_delay_s` | Configured delay in the fusion windowing | Affects how sensor streams are time-aligned. |
| `fusion_window_s` | Length of the fusion window in seconds | How much history goes into each fused “tick.” |
| `ball_poll_hz` | How often the ball reader was polled (nominal) | Expected spacing of ball-related samples during monitoring. |
| `ball_force_threshold` | **Configured** default ball trigger threshold from app config (`BALL_CONFIG`) at save time | **Not** the personalized `force_threshold` from calibration; see FAQ. |
| `calibration_values` | Object: EMG baselines/MVCs/threshold plus ball `baseline_force`, `mvc_force_peak`, `force_threshold`, percents | The numbers the game actually used after calibration; copied into session config as well. |
| `session_config_file` | Filename of the full snapshot (`session_config.json`) | Points to the detailed settings file for this run. |

---

## `session_config.json`

A **snapshot** of settings and calibration at session end: session paths, control mode, connection rules, fusion config, ball device config, EMG rates, calibration tuning knobs, and logging options. Useful to know *exactly* what the software thought its configuration was, not just the short summary.

### Top-level sections

| Section / key | What it is | Why it matters |
|---------------|------------|----------------|
| `snapshot_version` | Version number for this JSON layout | If the format changes later, tools can branch on this. |
| `snapshot_time` | Wall-clock time when the snapshot was written | When the config was frozen to disk. |
| `session` | `user_id`, `session_id`, `data_dir`, start times, `gameplay_start_perf` | Locates the folder and ties timing anchors together. |
| `control` | Mode, labels, passive logging flags | Explains primary vs passive logging behavior. |
| `connections` | Requirements and allow-simulation flags | Reproducibility and debugging (hardware vs sim). |
| `calibration` | Same numeric keys as `calibration_values` in the summary (EMG + force fields) | Full calibration snapshot embedded in config. |
| `fusion` | `config` (rates, sensors, jump trigger definitions) and `runtime` | How EMG and ball signals were fused and what thresholds were wired for triggers in config (EMG threshold is often overridden by calibration). |
| `ball` | Device name, timeouts, poll rates, **default** force thresholds for triggers and calibration feedback | Distinguishes factory/config thresholds from personalized `force_threshold` in `calibration`. |
| `emg_core` | Sampling rates, RMS settings, column name hints | Interpreting EMG-related CSV columns and rates. |
| `calibration_config` | Trial counts, durations, quality thresholds | How strict the calibration wizard was. |
| `data_logging` | What to save, formats, batching, auto-plot | Whether you expect CSVs/plots for every session. |

---

## `calibration/calibration_results.json`

The **final calibration outcome** after the calibration wizard finishes. Written by `save_calibration_data` in `emg_jump_game.py` (merging the advanced calibration EMG result with ball-force fields computed in `_finalize_ball_force_calibration`).

| Field | What it is | Why it matters |
|--------|--------------|----------------|
| `baseline_left`, `baseline_right` | Typical “rest” EMG level per channel | Used to normalize muscle activation from “off” to “on.” |
| `mvc_left`, `mvc_right` | Maximum voluntary contraction level per side (or summary value) | Top of the useful EMG range for that session. |
| `mvc_left_peak`, `mvc_right_peak` | Peak values kept for normalization | Gameplay uses peaks when present for span calculations. |
| `threshold` | **EMG** jump threshold on the normalized / processed scale after calibration | Primary value for EMG-mode jump detection (also written into fusion updates). |
| `mvc_threshold_percent` | User-facing percent that produced the EMG `threshold` | Easier to report than the raw threshold float. |
| `baseline_force` | Estimated “resting” ball force from calibration samples (10th percentile of collected force values) | Bottom of the personalized force range. |
| `mvc_force_peak` | Maximum ball force seen during calibration (from the same pooled samples) | Top of the personalized force range. |
| `force_threshold` | Ball jump threshold derived from `baseline_force`, `mvc_force_peak`, and `force_mvc_threshold_percent` | Used when **force** mode is primary (fusion updates this on the force trigger). |
| `force_mvc_threshold_percent` | MVC-style percent along the force range for `force_threshold` | Same idea as EMG percent, but for squeeze force. |
| `sensitivity` | Calibration system sensitivity (if present) | May appear from the advanced calibration module. |
| `quality_score` | Automated quality score for the calibration (if present) | Quick check whether calibration met internal quality targets. |
| `warnings` | List of human-readable issues (if present) | Explains noisy baseline, low MVC, etc. |

---

## `calibration/calibration_squeeze_events.json`

Optional file: a JSON **array** of events. Each entry is one moment the ball monitor decided you crossed the **calibration feedback** squeeze threshold (not the same as every raw sample). Populated from `BallForceMonitor.calibration_squeeze_events` or a fallback list on the game controller, and only written if the list is non-empty.

| Field | What it is | Why it matters |
|--------|--------------|----------------|
| `timestamp` | Wall-clock `time.time()` when the event was recorded | Human-readable ordering and correlation with wall time. |
| `session_elapsed_s` | Seconds since the calibration session’s `perf_counter` anchor | Relative time within calibration. |
| `perf_counter` | High-resolution time associated with the sample (same clock family as gameplay fusion) | Line up with EMG/force CSV streams (see FAQ). |
| `source` | Usually `"calibration_squeeze"` | Labels this as calibration feedback, not a gameplay jump. |
| `force_value` | Ball force reading at detection | Shows how hard they squeezed when feedback fired. |
| `threshold` | The calibration feedback threshold used (from ball config) | Explains why this event fired. |
| `simulated` | Whether the ball path was simulated | Interpret magnitudes cautiously if `true`. |

---

## `gameplay/raw_emg_data.csv`

Per-sample EMG at the fusion output rate. Rows come from `EMGFusionPipeline._on_fused_frame` and are flushed in `save_session_data`.

| Column | What it is | Why it matters |
|--------|------------|----------------|
| `timestamp` | Fusion frame time: `time.perf_counter()` value carried as the frame’s `ts` | Same “stopwatch” clock as much of the rest of the pipeline — **not** Unix wall time. |
| `sample_timestamp` | Sample time from the frame (`sample_ts`), or the frame time if absent | Intended for the actual sample instant; often matches `timestamp` when the bus aligns them. |
| `left_raw` | Raw fused value for the configured left sensor (e.g. flexor) | Muscle signal before heavy normalization in this CSV. |
| `right_raw` | Raw fused value for the configured right sensor (e.g. extensor) | Same for the other channel. |

---

## `gameplay/processed_emg_data.csv`

Same timeline as raw, plus RMS-smoothed values and **normalized** “how hard are they squeezing” numbers (0–1) used for gameplay logic.

| Column | What it is | Why it matters |
|--------|------------|----------------|
| `timestamp` | Same as raw: perf-counter-based fusion time | Align rows with `raw_emg_data` and ball CSVs using `perf_counter`. |
| `sample_timestamp` | Same meaning as in raw CSV | Finer alignment if the bus distinguishes sample vs processing time. |
| `unityTimestamp`, `localTimestamp` | Currently set equal to `timestamp` in code | Legacy-friendly duplicate columns for tools expecting those names. |
| `emg1`, `emg2` | Left and right raw (same as `left_raw` / `right_raw` conceptually) | Parallel naming to older EMG processor conventions. |
| `rms1`, `rms2` | Short-window RMS of each channel | Smoother signal than raw; closer to what triggers see. |
| `left_processed`, `right_processed` | Normalized activation 0–1 from baseline to MVC span | Direct view of “how close to calibrated max” each side is. |

---

## `gameplay/jump_events.csv`

One row per detected jump during gameplay.

| Column | What it is | Why it matters |
|--------|------------|----------------|
| `event_id` | 1-based counter for the session’s logged jumps | Stable row order. |
| `timestamp` | Wall-clock `time.time()` when the jump was logged | When the jump happened in real-world time. |
| `session_elapsed_s` | Seconds since `gameplay_start_perf` using `time.perf_counter()` | Time since gameplay started, comparable to other perf_counter-based columns. |
| `source` | Which control path reported the jump (`emg`, `force`, etc.) | Tells you which trigger fired. |
| `control_mode` | App’s primary mode at that moment | May match `source` or clarify keyboard vs sensor. |
| `force_value` | Ball force feature at fire time (RMS of force if available, else raw) | How hard the ball was squeezed when the jump registered. |
| `left_value`, `right_value` | Normalized EMG features for left/right at fire time | Muscle state at jump. |
| `threshold` | Active trigger’s threshold at fire time | Explains the bar they had to cross (EMG threshold in EMG mode, or personalized force threshold in force mode when fusion has updated it). |
| `trigger_id` | Internal id of the trigger configuration (`jump`, `force_jump`, etc.) | Maps to `fusion.jump_triggers` in config. |
| `simulated` | Whether the firing path used simulated hardware | Provenance for research. |
| `perf_counter` | `time.perf_counter()` at emission in the fusion pipeline | High-resolution instant for sync with EMG/force CSV rows. |

---

## `gameplay/ball_force_samples.csv`

Time series of ball force during gameplay (from the fusion pipeline’s ball feature path). Only written if samples were buffered.

| Column | What it is | Why it matters |
|--------|------------|----------------|
| `timestamp` | Wall-clock `time.time()` when the fused frame was processed | Real-world time for each row. |
| `session_elapsed_s` | Fused frame `ts` minus the fusion pipeline’s `session_start_perf` | Elapsed time since gameplay fusion anchor. |
| `perf_counter` | Fused frame time (`ts`) — same clock family as EMG CSV `timestamp` | **Use this column** to align with `raw_emg_data` / `processed_emg_data` `timestamp` / `sample_timestamp`. |
| `force_raw` | Instantaneous fused ball force scalar | Direct reading from the fused “ball” channel. |
| `force_rms` | Rolling RMS of `force_raw` | Smoother signal; often what force-based jump detection uses when RMS mode is on. |

---

## FAQ

### Are MVC **force** squeezes detected during calibration and saved?

**Yes, in two complementary ways:**

1. **`calibration_results.json`** stores **summary statistics**, not every squeeze: after calibration completes, the game computes `baseline_force` (low end of the observed force distribution), `mvc_force_peak` (max observed), and from those derives `force_threshold` (and `force_mvc_threshold_percent`). Those are the “MVC-style” force calibration outcomes.
2. **`calibration_squeeze_events.json`** stores **individual squeeze events** whenever the ball monitor’s calibration feedback trigger fires (threshold crossings during calibration). Each row-like object includes `force_value`, `perf_counter`, and `threshold`.

So: **aggregated numbers** → `calibration_results.json`; **event-by-event log** → `calibration_squeeze_events.json` (if any events occurred).

### Is the **force threshold** used during gameplay saved from calibration?

**Yes.** Look for:

- `calibration_values.force_threshold` inside **`session_summary.json`**
- The same keys under **`session_config.json`** → `calibration.force_threshold`

After calibration, the fusion pipeline’s force trigger is updated from `calibration_values` (`update_calibration` in `emg_fusion_pipeline.py`), so gameplay force mode uses that personalized value.

**Important distinction:** `session_summary.json` also has top-level `ball_force_threshold`. That field is copied from **`BALL_CONFIG['force_threshold']`** (the default config value at save time), **not** the personalized `calibration_values.force_threshold`. For “what threshold did *this person’s calibration* produce,” use **`calibration_values.force_threshold`** (and the same key in `session_config.json` → `calibration`).

### What is `perf_counter` vs wall-clock `timestamp`?

- **`time.perf_counter()`** (what CSV/JSON usually label `perf_counter`, or the EMG CSV columns `timestamp` / `sample_timestamp` when filled from fusion frames): a **monotonic high-resolution stopwatch** in seconds. It does **not** tell you the time of day. It is ideal for **aligning two signals** recorded in the same process (subtract two values to get a precise interval; match values across CSVs).
- **Wall-clock timestamps** (Unix seconds like `1778775810.21…`, or labels described as `time.time()` in code): tell you **when** something happened in real time. They can be affected by system clock adjustments, so they are better for diaries and less ideal for sub-millisecond alignment.

**Rule of thumb:** use **`perf_counter` (and EMG fusion `timestamp` / `sample_timestamp`)** to line up EMG, ball, and jump rows; use **`timestamp` where it is clearly `time.time()`** (for example `ball_force_samples.csv`’s first column or jump event wall time) when you care about clock time or date.

---

## Code reference (read-only)

| Topic | Primary location |
|--------|------------------|
| Saving calibration JSON and squeeze log | `emg_jump_game.py` → `save_calibration_data` |
| Ball monitoring and squeeze events | `ball_force_monitor.py` → `BallForceMonitor` (`calibration_squeeze_events`, `_emit_calibration_squeeze`) |
| Force baseline / peak / threshold from calibration samples | `emg_jump_game.py` → `_finalize_ball_force_calibration`, `force_threshold_from_percent` |
| EMG calibration wizard | `advanced_calibration.py` (integrated as `AdvancedCalibrationSystem` in `emg_jump_game.py`) |
| Fusion row timestamps and buffers | `emg_fusion_pipeline.py` → `_on_fused_frame`, `_emit_jump` |
| Session summary and CSV field names | `emg_jump_game.py` → `save_session_data` |

No game Python files were modified to produce this guide; only this document was added under `docs/`.

---

**Interactive plots:** `python plot_session_interactive.py GameData/<user>/<session>` or `python plot_session_interactive.py --latest <user>` — see [INTERACTIVE_PLOTS.md](INTERACTIVE_PLOTS.md).
