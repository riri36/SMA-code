#!/usr/bin/env python3
"""
Enhanced EMG-Controlled Vertical Jump Game
Features:
- Previous calibration loading for returning users
- Threshold adjustment after calibration
- Improved user experience
"""

import pygame
import sys
import time
import json
import csv
import numpy as np
from pathlib import Path
from datetime import datetime
from enum import Enum
import random
import math
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Import EMG system components
from advanced_calibration import AdvancedCalibrationSystem
from delsys_interface import DelsysInterface
# FUSION ADDITION: threaded fusion pipeline for gameplay jump detection.
from emg_fusion_pipeline import EMGFusionPipeline
from ball_force_monitor import BallForceMonitor
from config import (
    BALL_CONFIG,
    CALIBRATION_CONFIG,
    CONNECTION_CONFIG,
    DATA_LOGGING,
    EMG_CORE_CONFIG,
    FUSION_CONFIG,
    GAMEPLAY_CONTROL_CONFIG,
)

# Import game components
from python_pygame_version import (
    Player,
    Pipe,
    Camera,
    GROUND_HEIGHT,
    GRASS_COLOR,
    GROUND_COLOR,
    SCREEN_WIDTH as GAME_WORLD_WIDTH,
    SCREEN_HEIGHT as GAME_WORLD_HEIGHT,
)

from ui.hapticare_shell import (
    NAV_HEIGHT,
    NAV_LABELS,
    content_rect,
    draw_bottom_nav,
    draw_placeholder,
    nav_hit_test,
)
from ui.theme import default_light_theme, fill_for_gameplay, fill_for_shell_screen
from ui.calibration_paint import draw_smooth_progress, draw_title_card, draw_sensor_node


# =====================================
# GAME STATES
# =====================================

class GameState(Enum):
    INITIALIZATION = 0    # Checking connections
    USER_INPUT = 1        # Getting user ID
    CONNECTION_VERIFY = 11  # Verify Delsys EMG + HapticBall paths
    USER_CHOICE = 2       # Choose to use existing or recalibrate
    CALIBRATION = 3       # Running calibration
    THRESHOLD_ADJUST = 4  # Adjust threshold after calibration
    TRIGGER_MODE_SELECT = 9  # Choose EMG, ball force, or Space jumps
    MENU = 5             # Main menu
    PLAYING = 6          # Gameplay
    GAME_OVER = 7        # Game over screen
    SESSION_END = 8      # Saving data


# =====================================
# EMG GAME CONTROLLER
# =====================================

class EMGGameController:
    """Manages EMG system integration with the game"""
    
    def __init__(self):
        self.emg_system = None
        self.delsys_interface = None
        self.calibration_system = None
        
        # Connection status
        self.python_connected = False
        self.delsys_connected = False
        self.calibration_complete = False
        
        # Session management
        self.user_id = ""
        self.session_id = None
        self.session_start_time = None
        self.data_dir = None
        
        # Data logging
        self.raw_data_buffer = []
        self.jump_events = []
        self.processed_emg_buffer = []
        
        # Calibration results
        self.calibration_values = {
            'baseline_left': 0.05,
            'baseline_right': 0.05,
            'mvc_left': 0.8,
            'mvc_right': 0.8,
            'mvc_left_peak': 0.8,
            'mvc_right_peak': 0.8,
            'threshold': 0.3,
            'mvc_threshold_percent': CALIBRATION_CONFIG['default_mvc_threshold_percent'],
            'baseline_force': None,
            'mvc_force_peak': None,
            'force_threshold': None,
            'force_mvc_threshold_percent': CALIBRATION_CONFIG['default_mvc_threshold_percent'],
        }
        
        # FUSION ADDITION: gameplay EMG path uses the fusion pipeline.
        self.fusion_pipeline = None
        self.control_mode = GAMEPLAY_CONTROL_CONFIG["default_mode"]
        self.ball_monitor = None
        self.gameplay_start_time = None
        self.gameplay_start_perf = None
        self.force_samples_buffer = []
        self._jump_event_seq = 0
        self.ball_connection_message = "Not connected"
        self.emg_connection_message = "Checking Delsys EMG path..."
        self.emg_connection_verified = False
        self.ball_connection_verified = False
        self.emg_using_simulation = False
        self.ball_using_simulation = False
        self.ball_hardware_connected = False
        self.calibration_squeeze_events = []
        self._pending_calibration_feedback = None
        self._calibration_feedback_lock = threading.Lock()
        self._calibration_session_perf = None
        self._session_plots_done = False
        # Prevents duplicate CSV/summary/plots when save_and_exit() and run() cleanup() both run.
        self._session_save_completed = False
        # Connection verify: align verified flags with live I/O (see May12 ConnectionCheck build).
        self._connection_verify_accept_emg_sim = CONNECTION_CONFIG["allow_emg_simulation"]
        self._ball_verify_last_force_perf = None
        # Background HapticBall connect (Enter / C) so pygame main thread keeps pumping events.
        self._ensure_ball_bg_thread: Optional[threading.Thread] = None
        self._ensure_ball_bg_start_lock = threading.Lock()

    def ball_connect_background_busy(self) -> bool:
        """True while a daemon thread is running ``ensure_ball_connection()``."""
        t = self._ensure_ball_bg_thread
        return t is not None and t.is_alive()

    def start_ensure_ball_connection_background(self) -> None:
        """Start ``ensure_ball_connection()`` on a worker thread if none is running."""
        with self._ensure_ball_bg_start_lock:
            if self._ensure_ball_bg_thread is not None and self._ensure_ball_bg_thread.is_alive():
                return

            def worker() -> None:
                try:
                    self.ensure_ball_connection()
                except Exception:
                    logger.exception("Background ensure_ball_connection failed")

            self._ensure_ball_bg_thread = threading.Thread(
                target=worker,
                name="ensure-ball-bg",
                daemon=True,
            )
            self._ensure_ball_bg_thread.start()

    def _join_ensure_ball_background(self, timeout_s: float) -> None:
        t = self._ensure_ball_bg_thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout_s)
            if t.is_alive():
                logger.warning(
                    "Ball connect thread still running after %.1fs join; "
                    "reset may race with in-flight connect.",
                    timeout_s,
                )

    def _sync_delsys_connection_flags(self):
        """Mirror DelsysInterface hardware/simulation state into controller flags."""
        if not self.delsys_interface:
            self.delsys_connected = False
            self.emg_using_simulation = True
            return
        self.delsys_connected = self.delsys_interface.is_hardware_connected
        self.emg_using_simulation = self.delsys_interface.simulation_mode

    def _emg_status_label(self):
        """Human-readable Delsys path for init/verify screens."""
        if self.delsys_connected:
            return "Hardware"
        if self.emg_using_simulation:
            return "Simulation"
        return "Not connected"

    def _ball_status_label(self):
        """Human-readable HapticBall path for init/verify screens."""
        if self.ball_hardware_connected:
            return "Hardware"
        if self.ball_using_simulation:
            return "Simulation"
        return "Not connected"

    def _refresh_emg_connection_message(self):
        """Update EMG status text from current Delsys flags."""
        self._sync_delsys_connection_flags()
        self.emg_connection_message = self._emg_status_label()

    def _refresh_ball_connection_message(self):
        """Update ball status text from verified hardware/simulation flags."""
        self.ball_connection_message = self._ball_status_label()

    def _sync_connection_verified_from_live_io(
        self, *, update_emg: bool = True, update_ball: bool = True
    ):
        """Align verified flags with live I/O (connection verify screen).

        Ported from VerticalJumpPython_ConnectionCheck_May12: marks the ball path verified
        when fresh force samples arrive even if ``connection_status`` lagged.
        """
        poll_hz = max(float(BALL_CONFIG["poll_hz"]), 1.0)
        ball_fresh_s = max(0.5, 4.0 / poll_hz)

        self._sync_delsys_connection_flags()
        iface = self.delsys_interface
        if iface and update_emg:
            try:
                iface.get_emg_data_with_timestamps()
            except Exception:
                pass

        prev_emg = self.emg_connection_verified
        prev_ball = self.ball_connection_verified

        if update_emg:
            new_emg = False
            emg_reason = "no Delsys interface"
            if iface:
                if self.delsys_connected:
                    new_emg = True
                    t = getattr(iface, "last_emg_packet_wall_time", None)
                    if t is not None and (time.time() - t) < 3.0:
                        emg_reason = "Delsys hardware connected (live EMG)"
                    else:
                        emg_reason = "Delsys hardware connected"
                elif self.emg_using_simulation and self._connection_verify_accept_emg_sim:
                    new_emg = True
                    emg_reason = "EMG simulation allowed (live pull)"
                else:
                    new_emg = False
                    emg_reason = "EMG path not ready"
        else:
            new_emg = prev_emg
            emg_reason = "EMG left unchanged"

        if update_ball:
            new_ball = False
            ball_reason = "no ball monitor"
            mon = self.ball_monitor
            if mon is None:
                self._ball_verify_last_force_perf = None
            else:
                st_ok = mon.connection_status in ("connected", "simulated")
                lf = None
                try:
                    lf = mon.latest_force()
                except Exception:
                    lf = None
                if lf is not None:
                    self._ball_verify_last_force_perf = time.perf_counter()
                lp = getattr(mon, "last_sample_perf", None)
                monitor_fresh = lp is not None and (
                    time.perf_counter() - float(lp) < ball_fresh_s
                )
                reader_fresh = (
                    self._ball_verify_last_force_perf is not None
                    and (
                        time.perf_counter() - self._ball_verify_last_force_perf
                        < ball_fresh_s
                    )
                )
                sample_fresh = monitor_fresh or reader_fresh
                new_ball = st_ok or (lf is not None and sample_fresh)
                if new_ball:
                    self.ball_using_simulation = mon.using_simulation
                    self.ball_hardware_connected = (
                        mon.connection_status == "connected"
                        and not mon.using_simulation
                    )
                    ball_reason = (
                        "ball monitor connected"
                        if st_ok
                        else "live ball force samples"
                    )
                else:
                    ball_reason = "ball path not ready"
        else:
            new_ball = prev_ball
            ball_reason = "Ball left unchanged"

        if update_emg and new_emg != prev_emg:
            logger.info(
                "connection_verify emg_connection_verified %s -> %s (%s)",
                prev_emg,
                new_emg,
                emg_reason,
            )
        if update_ball and new_ball != prev_ball:
            logger.info(
                "connection_verify ball_connection_verified %s -> %s (%s)",
                prev_ball,
                new_ball,
                ball_reason,
            )

        if update_emg:
            self.emg_connection_verified = new_emg
        if update_ball:
            self.ball_connection_verified = new_ball

        if update_emg:
            self._refresh_emg_connection_message()
        if update_ball:
            self._refresh_ball_connection_message()

    def _initialize_ball_connection(self):
        """FUSION ADDITION: probe HapticBall hardware without verifying or streaming."""
        from input_HapticBall_interface import HapticBallReader

        probe = HapticBallReader(
            simulate=False,
            device_name=BALL_CONFIG["device_name"],
            scan_timeout_s=min(float(BALL_CONFIG["scan_timeout_s"]), 2.0),
            queue_size=int(BALL_CONFIG["queue_size"]),
            keep_duration=float(BALL_CONFIG["keep_duration"]),
        )
        hardware_found = probe.probe_hardware()
        self.ball_hardware_connected = hardware_found
        if hardware_found:
            self.ball_using_simulation = False
        elif CONNECTION_CONFIG["allow_ball_simulation"]:
            self.ball_using_simulation = True
        else:
            self.ball_using_simulation = False
        self.ball_connection_verified = False
        self._refresh_ball_connection_message()
        return hardware_found or self.ball_using_simulation

    def ensure_ball_connection(self):
        """Connect the ball path with Delsys-style hardware-first simulation fallback."""
        connected = self.connect_ball(simulate=False, allow_sim_fallback=True)
        if connected:
            return True
        if CONNECTION_CONFIG["allow_ball_simulation"]:
            return self.connect_ball(simulate=False, allow_sim_fallback=True)
        return False
    
    def _try_early_ball_hardware_before_delsys(self) -> None:
        """Optional: spend up to ``early_ball_init_max_s`` on hardware ball only, then stop.

        Delsys initialization always runs afterward even if this times out or fails.
        Simulation fallback is **not** used here so EMG can start without a fake ball.
        """
        max_wall = float(BALL_CONFIG.get("early_ball_init_max_s", 0.0))
        if max_wall <= 0:
            return
        done = threading.Event()

        def run() -> None:
            try:
                self.connect_ball(simulate=False, allow_sim_fallback=False)
            except Exception:
                logger.exception("Early init hardware ball connect failed")
            finally:
                done.set()

        thread = threading.Thread(target=run, name="init-early-ball", daemon=True)
        thread.start()
        if not done.wait(timeout=max_wall):
            print(
                f"Ball: hardware connect still in progress after {max_wall:.0f}s; "
                "stopping attempt and continuing with Delsys (retry ball on verify screen)."
            )
            self.stop_ball_monitor()
            self.ball_connection_verified = False
            self._initialize_ball_connection()
            self._refresh_ball_connection_message()
        thread.join(timeout=5.0)
        
        
    def initialize(self):
        """Initialize EMG system components"""
        try:
            print("Initializing EMG system...")
            
            # CONNECTION INTEGRATION: probe HapticBall alongside Delsys startup.
            self._initialize_ball_connection()

            self._try_early_ball_hardware_before_delsys()

            # Initialize Delsys interface
            self.delsys_interface = DelsysInterface()
            self.delsys_interface.initialize()
            self._sync_delsys_connection_flags()
            self._refresh_emg_connection_message()

            
            # Initialize calibration system
            self.calibration_system = AdvancedCalibrationSystem(
                unity_communication_callback=self.handle_calibration_message,
                delsys_interface=self.delsys_interface
            )
            
            self.python_connected = True
            print(
                "EMG System initialized. "
                f"Delsys hardware: {self.delsys_connected}, "
                f"EMG simulation: {self.emg_using_simulation}, "
                f"Ball hardware: {self.ball_hardware_connected}, "
                f"Ball simulation: {self.ball_using_simulation}"
            )
            return True
            
        except Exception as e:
            print(f"Failed to initialize EMG system: {e}")
            return False
    
    def create_session(self, user_id):
        """Create a new game session"""
        self.user_id = user_id
        self.session_start_time = time.time()
        self._session_save_completed = False
        self._session_plots_done = False
        
        # Create data directory
        base_dir = Path("GameData")
        base_dir.mkdir(exist_ok=True)
        
        user_dir = base_dir / user_id
        user_dir.mkdir(exist_ok=True)
        
        # Check for existing calibration data
        existing_calibration = self._find_existing_calibration(user_dir)
        
        if existing_calibration:
            # Load existing calibration
            if self._load_existing_calibration(existing_calibration):
                # Create new session for this gameplay
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.session_id = timestamp
                self.data_dir = user_dir / timestamp
                self.data_dir.mkdir(exist_ok=True)
                
                # Create subdirectories
                (self.data_dir / "calibration").mkdir(exist_ok=True)
                (self.data_dir / "gameplay").mkdir(exist_ok=True)
                
                # Copy calibration data to new session
                import shutil
                shutil.copy2(existing_calibration, self.data_dir / "calibration" / "calibration_results.json")
                
                print(f"New gameplay session created: {self.data_dir}")
            else:
                # Fall back to new calibration
                self._create_new_session(user_dir)
        else:
            # No existing calibration, create new session
            self._create_new_session(user_dir)
    
    def _find_existing_calibration(self, user_dir):
        """Find the most recent calibration data for a user"""
        if not user_dir.exists():
            return None
        
        # Look for calibration_results.json in any session subdirectory
        calibration_files = list(user_dir.glob("*/calibration/calibration_results.json"))
        
        if not calibration_files:
            return None
        
        # Return the most recent calibration file (by modification time)
        most_recent = max(calibration_files, key=lambda f: f.stat().st_mtime)
        return most_recent
    
    def _load_existing_calibration(self, calibration_file):
        """Load existing calibration data from file"""
        try:
            with open(calibration_file, 'r') as f:
                calibration_data = json.load(f)
            
            # Update calibration values
            self.calibration_values = {
                'baseline_left': calibration_data.get('baseline_left', 0.05),
                'baseline_right': calibration_data.get('baseline_right', 0.05),
                'mvc_left': calibration_data.get('mvc_left', calibration_data.get('mvc_left_peak', 0.8)),
                'mvc_right': calibration_data.get('mvc_right', calibration_data.get('mvc_right_peak', 0.8)),
                'mvc_left_peak': calibration_data.get('mvc_left_peak', calibration_data.get('mvc_left', 0.8)),
                'mvc_right_peak': calibration_data.get('mvc_right_peak', calibration_data.get('mvc_right', 0.8)),
                'threshold': calibration_data.get('threshold', 0.3),
                'mvc_threshold_percent': calibration_data.get(
                    'mvc_threshold_percent',
                    CALIBRATION_CONFIG['default_mvc_threshold_percent'],
                ),
                'baseline_force': calibration_data.get('baseline_force'),
                'mvc_force_peak': calibration_data.get('mvc_force_peak'),
                'force_threshold': calibration_data.get('force_threshold'),
                'force_mvc_threshold_percent': calibration_data.get(
                    'force_mvc_threshold_percent',
                    calibration_data.get(
                        'mvc_threshold_percent',
                        CALIBRATION_CONFIG['default_mvc_threshold_percent'],
                    ),
                ),
            }
            self._normalize_calibration_peaks()
            if 'mvc_threshold_percent' not in calibration_data:
                self.calibration_values['mvc_threshold_percent'] = (
                    self.estimate_mvc_threshold_percent(self.calibration_values)
                )
            
            # Mark calibration as complete
            self.calibration_complete = True
            
            print(f"✅ Loaded existing calibration:")
            print(f"   Threshold: {self.calibration_values['threshold']:.3f}")
            print(f"   From session: {calibration_file.parent.parent.name}")
            
            return True
            
        except Exception as e:
            print(f"Error loading existing calibration: {e}")
            return False
    
    def _create_new_session(self, user_dir):
        """Create a new session for calibration"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = timestamp
        self.data_dir = user_dir / timestamp
        self.data_dir.mkdir(exist_ok=True)
        
        # Create subdirectories
        (self.data_dir / "calibration").mkdir(exist_ok=True)
        (self.data_dir / "gameplay").mkdir(exist_ok=True)
        
        # Update calibration system with session path
        if self.calibration_system:
            self.calibration_system.session_path = str(self.data_dir)
        
        print(f"New calibration session created: {self.data_dir}")
    
    def _normalize_calibration_peaks(self, values=None):
        """Ensure EMG MVC peak keys exist before threshold UI."""
        values = self.calibration_values if values is None else values
        for side in ('left', 'right'):
            mvc_key = f'mvc_{side}'
            peak_key = f'mvc_{side}_peak'
            if values.get(peak_key) is None and values.get(mvc_key) is not None:
                values[peak_key] = values[mvc_key]
            if values.get(mvc_key) is None and values.get(peak_key) is not None:
                values[mvc_key] = values[peak_key]
        return values

    def _mvc_span(self, side, calibration_values=None):
        values = self._normalize_calibration_peaks(
            calibration_values or self.calibration_values
        )
        baseline = float(values.get(f'baseline_{side}', 0.05))
        peak_key = f'mvc_{side}_peak'
        mvc = float(values.get(peak_key, values.get(f'mvc_{side}', 0.8)))
        return baseline, mvc, max(mvc - baseline, 1e-6)

    def threshold_from_mvc_percent(self, percent, calibration_values=None):
        """Compute fused threshold from MVC-range percent across both channels."""
        values = calibration_values or self.calibration_values
        channel_thresholds = []
        for side in ('left', 'right'):
            baseline, mvc, span = self._mvc_span(side, values)
            channel_thresholds.append(baseline + (float(percent) / 100.0) * span)
        return max(channel_thresholds)

    def force_threshold_from_percent(self, percent, calibration_values=None):
        """Compute ball threshold from MVC-style percent of force range."""
        values = calibration_values or self.calibration_values
        baseline = values.get('baseline_force')
        peak = values.get('mvc_force_peak')
        if baseline is None or peak is None:
            return float(BALL_CONFIG['force_threshold'])
        span = max(float(peak) - float(baseline), 1e-6)
        return float(baseline) + (float(percent) / 100.0) * span

    def estimate_mvc_threshold_percent(self, calibration_values=None):
        """Estimate MVC-range percent from the current threshold value."""
        values = self._normalize_calibration_peaks(
            calibration_values or self.calibration_values
        )
        threshold = float(values.get('threshold', 0.3))
        channel_percents = []
        for side in ('left', 'right'):
            baseline, mvc, span = self._mvc_span(side, values)
            channel_percents.append(((threshold - baseline) / span) * 100.0)
        return max(
            CALIBRATION_CONFIG['mvc_threshold_percent_min'],
            min(
                CALIBRATION_CONFIG['mvc_threshold_percent_max'],
                round(max(channel_percents)),
            ),
        )

    def _threshold_is_valid(self, new_threshold):
        """Validate threshold against calibrated baseline/MVC bounds."""
        baselines = [
            float(self.calibration_values.get('baseline_left', 0.05)),
            float(self.calibration_values.get('baseline_right', 0.05)),
        ]
        mvcs = [
            self._mvc_span('left')[1],
            self._mvc_span('right')[1],
        ]
        min_baseline = min(baselines)
        max_mvc = max(mvcs)
        if max_mvc > min_baseline:
            return min_baseline <= new_threshold <= max_mvc
        return 0.05 <= new_threshold <= 1.0

    def apply_mvc_threshold_percent(self, percent, primary_mode=None):
        """Apply MVC-range percent to the active primary trigger threshold."""
        percent = float(percent)
        min_percent = CALIBRATION_CONFIG['mvc_threshold_percent_min']
        max_percent = CALIBRATION_CONFIG['mvc_threshold_percent_max']
        if not min_percent <= percent <= max_percent:
            return False
        mode = primary_mode or self.control_mode
        if mode == 'force':
            force_threshold = self.force_threshold_from_percent(percent)
            self.calibration_values['force_mvc_threshold_percent'] = percent
            self.calibration_values['force_threshold'] = force_threshold
            if self.fusion_pipeline:
                self.fusion_pipeline.update_calibration(self.calibration_values)
            print(f"Force threshold adjusted to: {force_threshold:.3f}")
            return True
        new_threshold = self.threshold_from_mvc_percent(percent)
        if not self._threshold_is_valid(new_threshold):
            return False
        self.calibration_values['mvc_threshold_percent'] = percent
        return self.adjust_threshold(new_threshold)

    def adjust_threshold(self, new_threshold):
        """Adjust the threshold value"""
        if self._threshold_is_valid(new_threshold):
            self.calibration_values['threshold'] = new_threshold
            # FUSION ADDITION: keep fused trigger thresholds aligned with calibration.
            if self.fusion_pipeline:
                self.fusion_pipeline.update_calibration(self.calibration_values)
            print(f"Threshold adjusted to: {new_threshold:.3f}")
            return True
        return False

    def persist_calibration_threshold(self):
        """Persist the latest threshold and MVC percent to calibration JSON."""
        if not self.data_dir:
            return
        cal_file = self.data_dir / "calibration" / "calibration_results.json"
        payload = dict(self.calibration_values)
        if cal_file.exists():
            try:
                with open(cal_file, 'r') as f:
                    payload.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                pass
        payload.update(self.calibration_values)
        with open(cal_file, 'w') as f:
            json.dump(payload, f, indent=2)
        
    def start_calibration(self):
        """Start the calibration process"""
        self.calibration_squeeze_events = []
        self._calibration_session_perf = time.perf_counter()
        self.begin_calibration_ball_monitoring()
        if self.calibration_system:
            self.calibration_system.start_calibration_sequence()
            return True
        return False

    def begin_calibration_ball_monitoring(self):
        """FUSION ADDITION: keep the ball reader alive and emit squeeze feedback during calibration."""
        if self.ball_monitor is None:
            if self.ball_connection_verified:
                self.ball_monitor = BallForceMonitor(simulate=self.ball_using_simulation)
                self.ball_monitor.connect()
            elif CONNECTION_CONFIG["allow_ball_simulation"]:
                self.connect_ball(simulate=True)
            else:
                self.connect_ball(simulate=False)
        if not self.ball_monitor:
            return
        self.ball_monitor.session_start_perf = (
            self._calibration_session_perf or time.perf_counter()
        )
        self.ball_monitor.set_calibration_feedback(
            True,
            callback=self._on_calibration_ball_squeeze,
        )
        self.ball_monitor.start_monitoring()

    def end_calibration_ball_feedback(self):
        """Stop calibration squeeze callbacks while keeping the verified ball connection."""
        if self.ball_monitor:
            self.ball_monitor.set_calibration_feedback(False)

    def _on_calibration_ball_squeeze(self, event):
        """Queue on-screen calibration feedback for a detected ball squeeze."""
        with self._calibration_feedback_lock:
            self._pending_calibration_feedback = {
                'source': 'ball',
                'reason': 'Ball squeeze detected',
                'force_value': event.get('force_value'),
                'threshold': event.get('threshold'),
                'simulated': event.get('simulated', False),
                'timestamp': event.get('timestamp', time.time()),
            }
        self.calibration_squeeze_events.append(dict(event))

    def consume_calibration_feedback(self):
        """Return and clear the next pending calibration feedback event."""
        with self._calibration_feedback_lock:
            pending = self._pending_calibration_feedback
            self._pending_calibration_feedback = None
        return pending
    
    def _finalize_ball_force_calibration(self):
        """FUSION ADDITION: derive ball baseline/peak MVC from calibration samples."""
        force_values = []
        if self.ball_monitor and self.ball_monitor.force_samples:
            for sample in self.ball_monitor.force_samples:
                value = sample.get('force_rms', sample.get('force_raw'))
                if value is not None:
                    force_values.append(float(value))
        for event in self.calibration_squeeze_events:
            value = event.get('force_value')
            if value is not None:
                force_values.append(float(value))
        if not force_values:
            return
        baseline_force = float(np.percentile(force_values, 10))
        mvc_force_peak = float(np.max(force_values))
        default_percent = CALIBRATION_CONFIG['default_mvc_threshold_percent']
        self.calibration_values['baseline_force'] = baseline_force
        self.calibration_values['mvc_force_peak'] = mvc_force_peak
        self.calibration_values['force_mvc_threshold_percent'] = default_percent
        self.calibration_values['force_threshold'] = self.force_threshold_from_percent(
            default_percent,
            self.calibration_values,
        )

    def handle_calibration_message(self, data):
        """Handle calibration system messages"""
        msg_type = data.get('type', '')
        command = data.get('command', '')

        if msg_type == 'calibration_phase_started':
            with self._calibration_feedback_lock:
                self._pending_calibration_feedback = {
                    'source': 'phase',
                    'phase': data.get('phase'),
                    'trial': data.get('trial'),
                    'reason': data.get('instruction', 'Calibration phase started'),
                    'timestamp': data.get('timestamp', time.time()),
                }
        elif command == 'jump':
            with self._calibration_feedback_lock:
                self._pending_calibration_feedback = {
                    'source': data.get('source', 'emg'),
                    'phase': data.get('phase'),
                    'reason': data.get('reason', 'Calibration feedback'),
                    'left_value': data.get('leftValue'),
                    'right_value': data.get('rightValue'),
                    'threshold': data.get('threshold'),
                    'timestamp': data.get('timestamp', time.time()),
                }
        elif msg_type == 'calibration_complete':
            result = data.get('result', {})
            self._finalize_ball_force_calibration()
            self.calibration_values = {
                'baseline_left': result.get('baseline_left', 0.05),
                'baseline_right': result.get('baseline_right', 0.05),
                'mvc_left': result.get('mvc_left', result.get('mvc_left_peak', 0.8)),
                'mvc_right': result.get('mvc_right', result.get('mvc_right_peak', 0.8)),
                'mvc_left_peak': result.get('mvc_left_peak', result.get('mvc_left', 0.8)),
                'mvc_right_peak': result.get('mvc_right_peak', result.get('mvc_right', 0.8)),
                'threshold': result.get('threshold', 0.3),
                'mvc_threshold_percent': result.get(
                    'mvc_threshold_percent',
                    CALIBRATION_CONFIG['default_mvc_threshold_percent'],
                ),
                'baseline_force': self.calibration_values.get('baseline_force'),
                'mvc_force_peak': self.calibration_values.get('mvc_force_peak'),
                'force_threshold': self.calibration_values.get('force_threshold'),
                'force_mvc_threshold_percent': self.calibration_values.get(
                    'force_mvc_threshold_percent',
                    CALIBRATION_CONFIG['default_mvc_threshold_percent'],
                ),
            }
            self._normalize_calibration_peaks()
            self.calibration_complete = True
            self.end_calibration_ball_feedback()
            payload = dict(result)
            payload.update(self.calibration_values)
            self.save_calibration_data(payload)
            print(f"Calibration complete! Threshold: {self.calibration_values['threshold']:.3f}")
    
    def start_emg_processing(self, passive_logging=None, control_mode=None, ball_reader=None):
        """Start the threaded fusion pipeline for gameplay logging/jump detection."""
        if self.fusion_pipeline:
            if control_mode is not None:
                self.fusion_pipeline.set_control_mode(control_mode)
            return
        if passive_logging is None:
            passive_logging = self.control_mode == "keyboard"
        if control_mode is None:
            control_mode = self.control_mode
        # FUSION ADDITION: EMG and ball force share the fusion bus and trigger loop.
        simulate_delsys = self.emg_using_simulation
        if ball_reader is None and self.ball_monitor:
            ball_reader = self.ball_monitor.reader
        self.fusion_pipeline = EMGFusionPipeline(
            self.calibration_values,
            control_mode=control_mode,
            simulate_delsys=simulate_delsys,
            simulate_ball=self.ball_using_simulation,
            ball_reader=ball_reader,
            passive_logging=passive_logging,
            session_start_perf=self.gameplay_start_perf or time.perf_counter(),
            delsys_interface=self.delsys_interface,
        )
        self.fusion_pipeline.start()
        mode = "passive logging" if control_mode == "keyboard" else "jump detection"
        print(f"EMG fusion processing started ({mode})")

    def stop_emg_processing(self):
        """Stop the fusion pipeline and sync gameplay logs."""
        if not self.fusion_pipeline:
            return
        self.fusion_pipeline.stop()
        self._sync_fusion_logs()
        self.fusion_pipeline = None
        print("EMG fusion processing stopped")

    def stop_ball_monitor(self):
        """Stop the HapticBall monitor used for connection and calibration."""
        if not self.ball_monitor:
            return
        self.ball_monitor.stop()
        self.ball_monitor = None

    def set_control_mode(self, mode):
        """Select gameplay jump source."""
        if mode not in GAMEPLAY_CONTROL_CONFIG["modes"]:
            return False
        self.control_mode = mode
        if self.fusion_pipeline:
            self.fusion_pipeline.set_control_mode(mode)
        return True

    def reconnect_emg_path(self, accept_simulation=False):
        """Re-run Delsys init and EMG verification (E key on verify screen)."""
        self.stop_emg_processing()
        if self.delsys_interface:
            try:
                print("Reconnecting EMG (Delsys re-initialize)...")
                self.delsys_interface.initialize()
            except Exception as exc:
                print(f"EMG reconnect failed: {exc}")
        self._sync_delsys_connection_flags()
        return self.verify_emg_connection(accept_simulation=accept_simulation)

    def reset_connection_verify_state(self):
        """Clear ball monitor and EMG fusion; drop verified flags (R key)."""
        self.stop_emg_processing()
        self._join_ensure_ball_background(3.0)
        self.stop_ball_monitor()
        self.emg_connection_verified = False
        self.ball_connection_verified = False
        self.ball_using_simulation = False
        self.ball_hardware_connected = False
        self._ball_verify_last_force_perf = None
        self._refresh_emg_connection_message()
        self._refresh_ball_connection_message()
        print("Connection verify reset: EMG fusion stopped, ball monitor cleared.")

    def poll_connection_verify_live_samples(self):
        """Optional live values for the verify screen (hardware vs simulation)."""
        emg_hw_lr = None
        emg_sim_lr = None
        ball_hw = None
        ball_sim = None
        if self.delsys_interface:
            try:
                data = self.delsys_interface.get_emg_data_with_timestamps()
                lr = (float(data["left"]), float(data["right"]))
                if self.delsys_connected:
                    emg_hw_lr = lr
                elif self.emg_using_simulation:
                    emg_sim_lr = lr
            except Exception:
                pass
        if self.ball_monitor:
            try:
                f = self.ball_monitor.latest_force()
            except Exception:
                f = None
            if f is not None:
                ball_hw_path = (
                    self.ball_monitor.connection_status == "connected"
                    and not self.ball_monitor.using_simulation
                )
                ball_sim_path = self.ball_monitor.using_simulation or (
                    self.ball_monitor.connection_status == "simulated"
                )
                if ball_hw_path:
                    ball_hw = float(f)
                elif ball_sim_path:
                    ball_sim = float(f)
        return {
            "emg_hw_lr": emg_hw_lr,
            "emg_sim_lr": emg_sim_lr,
            "ball_hw": ball_hw,
            "ball_sim": ball_sim,
        }

    def verify_emg_connection(self, accept_simulation=False):
        """Verify the Delsys EMG path is ready for the session."""
        self._connection_verify_accept_emg_sim = bool(accept_simulation)
        self._sync_connection_verified_from_live_io()
        return self.emg_connection_verified

    def verify_ball_connection(self):
        """Verify the HapticBall path is ready for the session."""
        self._sync_connection_verified_from_live_io()
        return self.ball_connection_verified

    def dual_connections_ready(self):
        """Return True when both EMG and ball paths are verified."""
        return self.emg_connection_verified and self.ball_connection_verified

    def begin_gameplay_session(self):
        """Mark gameplay start and start the unified fusion gameplay path."""
        self.stop_emg_processing()
        self.gameplay_start_time = time.time()
        self.gameplay_start_perf = time.perf_counter()
        self._jump_event_seq = 0
        self.jump_events = []
        self.force_samples_buffer = []
        ball_reader = None
        if self.ball_monitor:
            ball_reader = self.ball_monitor.release_reader()
        # FUSION ADDITION: primary trigger mode selects the active fused jump source.
        self.start_emg_processing(
            control_mode=self.control_mode,
            ball_reader=ball_reader,
        )

    def connect_ball(self, simulate=False, *, allow_sim_fallback: bool = True):
        """Connect to the HapticBall before gameplay.

        When ``allow_sim_fallback`` is False (early init), a failed hardware attempt
        does not immediately open the simulated ball path.
        """
        self.stop_ball_monitor()
        self.ball_monitor = BallForceMonitor(simulate=simulate)
        connected = self.ball_monitor.connect()
        if connected:
            self.ball_using_simulation = self.ball_monitor.using_simulation
            self.ball_hardware_connected = (
                self.ball_monitor.connection_status == "connected"
                and not self.ball_monitor.using_simulation
            )
            self.verify_ball_connection()
            return True
        if (
            allow_sim_fallback
            and not simulate
            and CONNECTION_CONFIG["allow_ball_simulation"]
            and not self.ball_monitor.using_simulation
        ):
            return self.connect_ball(simulate=True, allow_sim_fallback=True)
        self.ball_connection_verified = False
        self.ball_using_simulation = self.ball_monitor.using_simulation
        self.ball_hardware_connected = False
        self.ball_connection_message = (
            self.ball_monitor.reader.last_error
            or "Not connected"
        )
        return False

    def log_jump_event(self, source, **fields):
        """Record a gameplay jump with unified session timing."""
        self._jump_event_seq += 1
        elapsed = 0.0
        if self.gameplay_start_perf is not None:
            elapsed = time.perf_counter() - self.gameplay_start_perf
        event = {
            "event_id": self._jump_event_seq,
            "timestamp": time.time(),
            "session_elapsed_s": elapsed,
            "source": source,
            "control_mode": self.control_mode,
        }
        event.update(fields)
        self.jump_events.append(event)
        return event

    def _sync_fusion_logs(self):
        """Copy fusion pipeline buffers into the session logging fields."""
        if not self.fusion_pipeline:
            return
        self.raw_data_buffer = list(self.fusion_pipeline.raw_data_buffer)
        self.processed_emg_buffer = list(self.fusion_pipeline.processed_emg_buffer)
        if self.fusion_pipeline.ball_force_buffer:
            self.force_samples_buffer = list(self.fusion_pipeline.ball_force_buffer)

    def check_jump(self):
        """Check if the active gameplay control source fired a jump."""
        if self.control_mode in ("emg", "force") and self.fusion_pipeline:
            if self.fusion_pipeline.consume_jump():
                latest = self.fusion_pipeline.jump_events[-1] if self.fusion_pipeline.jump_events else {}
                source = self.control_mode
                self.log_jump_event(
                    source,
                    force_value=latest.get("force_value"),
                    left_value=latest.get("left_value"),
                    right_value=latest.get("right_value"),
                    threshold=latest.get("threshold"),
                    trigger_id=latest.get("trigger_id"),
                    simulated=latest.get("simulated", False),
                    perf_counter=latest.get("perf_counter"),
                )
                return True
        return False
    
    @staticmethod
    def _json_safe(value):
        """Convert runtime values into JSON-serializable primitives."""
        if isinstance(value, Enum):
            return value.name
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, dict):
            return {str(key): EMGGameController._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [EMGGameController._json_safe(item) for item in value]
        return value

    def build_session_config_snapshot(self):
        """Capture the full gameplay and system configuration for this session."""
        emg_primary = self.control_mode == "emg"
        force_primary = self.control_mode == "force"
        fusion_runtime = {}
        if self.fusion_pipeline:
            fusion_runtime = {
                "control_mode": self.fusion_pipeline.control_mode,
                "passive_logging": self.fusion_pipeline.passive_logging,
                "simulate_delsys": self.fusion_pipeline.simulate_delsys,
                "simulate_ball": self.fusion_pipeline.simulate_ball,
                "master_hz": self.fusion_pipeline.master_hz,
                "delay_s": self.fusion_pipeline.delay_s,
                "window_s": self.fusion_pipeline.window_s,
                "sensors": list(self.fusion_pipeline.sensors),
                "delsys_sensor_map": dict(self.fusion_pipeline.delsys_sensor_map),
                "left_sensor": self.fusion_pipeline.left_sensor,
                "right_sensor": self.fusion_pipeline.right_sensor,
                "ball_sensor": self.fusion_pipeline.ball_sensor,
                "rms_window": self.fusion_pipeline.rms_window,
                "ball_rms_window": self.fusion_pipeline.ball_rms_window,
                "trigger_source": (
                    self.fusion_pipeline._active_trigger.source
                    if self.fusion_pipeline._active_trigger is not None
                    else None
                ),
                "trigger_thread_started": self.fusion_pipeline.control_mode != "keyboard",
            }
        ball_runtime = {}
        if self.ball_monitor:
            ball_runtime = {
                "connection_status": self.ball_monitor.connection_status,
                "using_simulation": self.ball_monitor.using_simulation,
                "simulate_requested": self.ball_monitor.simulate_requested,
                "session_start_perf": self.ball_monitor.session_start_perf,
                "calibration_feedback_enabled": self.ball_monitor.calibration_feedback_enabled,
            }
        return {
            "snapshot_version": 1,
            "snapshot_time": time.time(),
            "session": {
                "user_id": self.user_id,
                "session_id": self.session_id,
                "data_dir": str(self.data_dir) if self.data_dir else None,
                "session_start_time": self.session_start_time,
                "gameplay_start_time": self.gameplay_start_time,
                "gameplay_start_perf": self.gameplay_start_perf,
            },
            "control": {
                "mode": self.control_mode,
                "available_modes": list(GAMEPLAY_CONTROL_CONFIG["modes"]),
                "mode_labels": dict(GAMEPLAY_CONTROL_CONFIG.get("mode_labels", {})),
                "default_mode": GAMEPLAY_CONTROL_CONFIG["default_mode"],
                "emg_primary": emg_primary,
                "force_primary": force_primary,
                "keyboard_primary": self.control_mode == "keyboard",
                "passive_emg_logging": not emg_primary,
                "passive_ball_logging": not force_primary,
                "configured_passive_emg_logging": GAMEPLAY_CONTROL_CONFIG["passive_emg_logging"],
                "configured_passive_ball_logging": GAMEPLAY_CONTROL_CONFIG["passive_ball_logging"],
            },
            "connections": {
                "emg_verified": self.emg_connection_verified,
                "emg_simulated": self.emg_using_simulation,
                "emg_hardware_connected": self.delsys_connected,
                "ball_verified": self.ball_connection_verified,
                "ball_simulated": self.ball_using_simulation,
                "require_emg_path": CONNECTION_CONFIG["require_emg_path"],
                "require_ball_path": CONNECTION_CONFIG["require_ball_path"],
                "allow_emg_simulation": CONNECTION_CONFIG["allow_emg_simulation"],
                "allow_ball_simulation": CONNECTION_CONFIG["allow_ball_simulation"],
            },
            "calibration": dict(self.calibration_values),
            "fusion": {
                "config": dict(FUSION_CONFIG),
                "runtime": fusion_runtime,
            },
            "ball": {
                "config": dict(BALL_CONFIG),
                "runtime": ball_runtime,
            },
            "emg_core": dict(EMG_CORE_CONFIG),
            "calibration_config": dict(CALIBRATION_CONFIG),
            "data_logging": dict(DATA_LOGGING),
        }

    def save_session_config(self):
        """Persist the full session configuration snapshot to disk."""
        if not self.data_dir:
            return
        payload = self._json_safe(self.build_session_config_snapshot())
        config_file = self.data_dir / "session_config.json"
        with open(config_file, "w") as f:
            json.dump(payload, f, indent=2)

    def save_calibration_data(self, calibration_result):
        """Save calibration data"""
        if not self.data_dir:
            return
        
        cal_file = self.data_dir / "calibration" / "calibration_results.json"
        with open(cal_file, 'w') as f:
            json.dump(calibration_result, f, indent=2)

        # FUSION ADDITION: optional squeeze feedback log during calibration collection.
        squeeze_events = []
        if self.ball_monitor and self.ball_monitor.calibration_squeeze_events:
            squeeze_events = list(self.ball_monitor.calibration_squeeze_events)
        elif self.calibration_squeeze_events:
            squeeze_events = list(self.calibration_squeeze_events)
        if squeeze_events:
            squeeze_file = self.data_dir / "calibration" / "calibration_squeeze_events.json"
            with open(squeeze_file, 'w') as f:
                json.dump(squeeze_events, f, indent=2)
    
    def save_session_data(self):
        """Save all session data"""
        if not self.data_dir:
            return
        if self._session_save_completed:
            return

        print("Saving session data...")
        self._sync_fusion_logs()
        if self.ball_monitor and not self.force_samples_buffer:
            self.force_samples_buffer = list(self.ball_monitor.force_samples)
        
        # Save raw EMG data
        if self.raw_data_buffer:
            raw_file = self.data_dir / "gameplay" / "raw_emg_data.csv"
            with open(raw_file, 'w', newline='') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=['timestamp', 'sample_timestamp', 'left_raw', 'right_raw'],
                )
                writer.writeheader()
                writer.writerows(self.raw_data_buffer)
        
        # Save processed EMG data (matching emg_processor format)
        if self.processed_emg_buffer:
            proc_file = self.data_dir / "gameplay" / "processed_emg_data.csv"
            with open(proc_file, 'w', newline='') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        'timestamp',
                        'sample_timestamp',
                        'unityTimestamp',
                        'localTimestamp',
                        'emg1',
                        'emg2',
                        'rms1',
                        'rms2',
                        'left_processed',
                        'right_processed',
                    ],
                )
                writer.writeheader()
                writer.writerows(self.processed_emg_buffer)
        
        # Save jump events
        if self.jump_events:
            jump_file = self.data_dir / "gameplay" / "jump_events.csv"
            fieldnames = [
                "event_id",
                "timestamp",
                "session_elapsed_s",
                "source",
                "control_mode",
                "force_value",
                "left_value",
                "right_value",
                "threshold",
                "trigger_id",
                "simulated",
                "perf_counter",
            ]
            with open(jump_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.jump_events)

        # FUSION ADDITION: save synchronized force samples for post-analysis.
        if self.force_samples_buffer:
            force_file = self.data_dir / "gameplay" / "ball_force_samples.csv"
            with open(force_file, "w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["timestamp", "session_elapsed_s", "perf_counter", "force_raw", "force_rms"],
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(self.force_samples_buffer)
        
        self.save_session_config()

        # Save session summary
        summary = {
            'user_id': self.user_id,
            'session_id': self.session_id,
            'start_time': self.session_start_time,
            'end_time': time.time(),
            'duration': time.time() - self.session_start_time,
            'total_jumps': len(self.jump_events),
            'control_mode': self.control_mode,
            'mvc_threshold_percent': self.calibration_values.get('mvc_threshold_percent'),
            'connections': {
                'emg_verified': self.emg_connection_verified,
                'emg_simulated': self.emg_using_simulation,
                'emg_hardware_connected': self.delsys_connected,
                'ball_verified': self.ball_connection_verified,
                'ball_simulated': self.ball_using_simulation,
            },
            'ball_simulated': self.ball_using_simulation,
            'gameplay_start_time': self.gameplay_start_time,
            'gameplay_start_perf': self.gameplay_start_perf,
            'passive_emg_logging': self.control_mode != "emg",
            'passive_ball_logging': self.control_mode != "force",
            'fusion_master_hz': FUSION_CONFIG['master_hz'],
            'fusion_delay_s': FUSION_CONFIG['delay_s'],
            'fusion_window_s': FUSION_CONFIG.get('window_s', 1.0),
            'ball_poll_hz': BALL_CONFIG['poll_hz'],
            'ball_force_threshold': BALL_CONFIG['force_threshold'],
            'calibration_values': self.calibration_values,
            'session_config_file': 'session_config.json',
        }
        
        summary_file = self.data_dir / "session_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(self._json_safe(summary), f, indent=2)
        
        # FUSION ADDITION: optional session-end plots after CSV/JSON export.
        if DATA_LOGGING.get("auto_plot_session", False) and not self._session_plots_done:
            try:
                from session_plotter import auto_plot_session

                plot_paths = auto_plot_session(self.data_dir, controller=self)
                self._session_plots_done = True
                if plot_paths:
                    print(f"Session plots saved to {self.data_dir / 'plots'}")
            except Exception as exc:
                print(f"Session auto-plot skipped: {exc}")

        print(f"Session data saved to {self.data_dir}")

        if DATA_LOGGING.get("interactive_plot_on_session_end", False):
            try:
                from session_plotter import spawn_interactive_session_plots

                spawn_interactive_session_plots(self.data_dir)
            except Exception as exc:
                print(f"Interactive session plots skipped: {exc}")

        self._session_save_completed = True


# =====================================
# INTEGRATED GAME
# =====================================

class IntegratedEMGGame:
    """Main game class with EMG integration"""
    
    def __init__(self):
        pygame.init()
        
        # Display
        self.DEFAULT_SCREEN_WIDTH = 400
        self.DEFAULT_SCREEN_HEIGHT = 600
        self.SCREEN_WIDTH = self.DEFAULT_SCREEN_WIDTH
        self.SCREEN_HEIGHT = self.DEFAULT_SCREEN_HEIGHT
        # FUSION ADDITION: resizable window with optional macOS maximize.
        self.screen = pygame.display.set_mode(
            (self.SCREEN_WIDTH, self.SCREEN_HEIGHT),
            pygame.RESIZABLE,
        )
        pygame.display.set_caption("EMG-Controlled Vertical Jump")
        self._try_maximize_window()
        self.haptic_theme = default_light_theme()
        self.NAV_HEIGHT = NAV_HEIGHT
        self.haptic_nav_index = 2
        self._prev_state = None
        self.tiny_font = pygame.font.Font(None, 18)
        self._gameplay_world_surface = None
        self._gameplay_dest_rect = pygame.Rect(0, 0, GAME_WORLD_WIDTH, GAME_WORLD_HEIGHT)
        self._rebuild_layout_surfaces()
        
        # Timing
        self.clock = pygame.time.Clock()
        self.FPS = 60
        
        # Fonts
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.input_font = pygame.font.Font(None, 32)
        
        # EMG Controller
        self.emg_controller = EMGGameController()
        
        # Game state
        self.state = GameState.INITIALIZATION
        self.running = True
        
        # User input
        self.user_id_input = ""
        self.input_active = False
        
        # Calibration UI
        self.calibration_message = "Initializing calibration..."
        self.calibration_progress = 0.0
        self.calibration_feedback_until = 0.0
        self.calibration_feedback_label = ""
        self.calibration_feedback_source = ""
        self.calibration_phase_started_at = 0.0
        self.calibration_phase_duration = float(CALIBRATION_CONFIG["trial_duration"])
        self._layout_calibration_ui()
        
        # Threshold adjustment
        self.threshold_percent_input = ""
        self.threshold_percent_value = float(
            CALIBRATION_CONFIG['default_mvc_threshold_percent']
        )
        self.threshold_percent_error = ""
        self.adjustment_step = 1
        self.trigger_mode_index = 0
        self.threshold_adjust_enter_armed = False
        self.threshold_adjust_ready_after_ms = 0
        self.ball_connect_in_progress = False
        
        # Game components (from original game)
        self.reset_game_components()
        
    def reset_game_components(self):
        """Reset game components from original game"""
        self.player = Player()
        self.camera = Camera()
        self.pipes = []
        self.score = 0

        # Create initial pipes
        current_height = 160
        for _ in range(3):
            self.pipes.append(Pipe(current_height))
            current_height += random.randint(115, 125)
    def _try_maximize_window(self):
        """FUSION ADDITION: maximize the pygame window when the platform supports it."""
        if sys.platform != "darwin":
            return
        try:
            wm_info = pygame.display.get_wm_info()
            window_id = wm_info.get("window")
            if window_id is None:
                return
            from pygame._sdl2 import video as sdl2_video

            sdl2_video.Window.from_window_id(window_id).maximize()
        except Exception:
            pass

    def _layout_calibration_ui(self):
        """Position calibration feedback balls for the current window size."""
        floor_y = max(120, int(self.SCREEN_HEIGHT * 0.72))
        self.calibration_bounce_floor_y = floor_y
        if not hasattr(self, "calibration_balls"):
            self.calibration_balls = [
                {
                    "label": "EMG",
                    "base_x": self.SCREEN_WIDTH // 2 - 70,
                    "x": self.SCREEN_WIDTH // 2 - 70,
                    "y": float(floor_y),
                    "velocity": 0.0,
                    "radius": 16,
                    "color": (80, 170, 255),
                    "active_color": (255, 220, 0),
                },
                {
                    "label": "Ball",
                    "base_x": self.SCREEN_WIDTH // 2 + 70,
                    "x": self.SCREEN_WIDTH // 2 + 70,
                    "y": float(floor_y),
                    "velocity": 0.0,
                    "radius": 16,
                    "color": (80, 170, 255),
                    "active_color": (255, 140, 60),
                },
            ]
            return
        for index, ball in enumerate(self.calibration_balls):
            offset = -70 if index == 0 else 70
            ball["base_x"] = self.SCREEN_WIDTH // 2 + offset
            ball["x"] = ball["base_x"]
            ball["y"] = min(float(ball["y"]), float(floor_y))

    def _handle_window_resize(self, width, height):
        """Resize the pygame surface and keep UI layout within the new bounds."""
        width = max(self.DEFAULT_SCREEN_WIDTH, int(width))
        height = max(self.DEFAULT_SCREEN_HEIGHT, int(height))
        if self.screen.get_size() == (width, height):
            self._rebuild_layout_surfaces()
            self._layout_calibration_ui()
            return
        self.SCREEN_WIDTH = width
        self.SCREEN_HEIGHT = height
        self.screen = pygame.display.set_mode(
            (self.SCREEN_WIDTH, self.SCREEN_HEIGHT),
            pygame.RESIZABLE,
        )
        self._rebuild_layout_surfaces()
        self._layout_calibration_ui()

    @staticmethod
    def _resize_dimensions_from_event(event):
        """Return (width, height) for a window resize event, or None."""
        if event.type == pygame.VIDEORESIZE:
            size = getattr(event, "size", None)
            if size is not None:
                return int(size[0]), int(size[1])
            return int(event.w), int(event.h)
        win_resized = getattr(pygame, "WINDOWRESIZED", None)
        if win_resized is not None and event.type == win_resized:
            return int(event.x), int(event.y)
        win_size_changed = getattr(pygame, "WINDOWSIZECHANGED", None)
        if win_size_changed is not None and event.type == win_size_changed:
            return int(event.x), int(event.y)
        return None

    def _rebuild_layout_surfaces(self):
        """Reserve bottom strip for HaptiCare-style navigation; gameplay uses content area only."""
        fw, fh = self.screen.get_size()
        self._full_width, self._full_height = fw, fh
        self.SCREEN_WIDTH = fw
        self.SCREEN_HEIGHT = max(300, fh - self.NAV_HEIGHT)
        self.content_surface = self.screen.subsurface(content_rect(fw, fh))
        self._layout_gameplay_dest()

    def _layout_gameplay_dest(self) -> None:
        """Scale-to-fit destination for the fixed 400x600 gameplay world inside the content surface."""
        cw, ch = self.content_surface.get_size()
        ww, wh = GAME_WORLD_WIDTH, GAME_WORLD_HEIGHT
        scale = min(cw / float(ww), ch / float(wh)) if ww and wh else 1.0
        dw = max(1, int(round(ww * scale)))
        dh = max(1, int(round(wh * scale)))
        x = (cw - dw) // 2
        y = (ch - dh) // 2
        self._gameplay_dest_rect = pygame.Rect(x, y, dw, dh)

    def _workflow_nav_tab(self) -> int:
        """Which bottom-nav tab owns the current GameState (Flutter shell mapping)."""
        if self.state in (GameState.MENU, GameState.PLAYING, GameState.GAME_OVER):
            return 3
        if self.state == GameState.SESSION_END:
            return 0
        return 2

    def run(self):
        """Main game loop"""
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(self.FPS)
        
        # Cleanup
        self.cleanup()
        pygame.quit()
    
    def handle_events(self):
        """Handle all events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            dims = IntegratedEMGGame._resize_dimensions_from_event(event)
            if dims is not None:
                width, height = dims
                if width > 0 and height > 0:
                    self._handle_window_resize(width, height)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                idx = nav_hit_test(
                    event.pos, self._full_width, self._full_height
                )
                if idx is not None:
                    self.haptic_nav_index = idx

            # State-specific event handling
            if self.state == GameState.USER_INPUT:
                self.handle_user_input_events(event)
            elif self.state == GameState.CONNECTION_VERIFY:
                self.handle_connection_verify_events(event)
            elif self.state == GameState.USER_CHOICE:
                self.handle_user_choice_events(event)
            elif self.state == GameState.CALIBRATION:
                self.handle_calibration_events(event)
            elif self.state == GameState.THRESHOLD_ADJUST:
                self.handle_threshold_adjust_events(event)
            elif self.state == GameState.TRIGGER_MODE_SELECT:
                self.handle_trigger_mode_events(event)
            elif self.state == GameState.MENU:
                self.handle_menu_events(event)
            elif self.state == GameState.PLAYING:
                self.handle_game_events(event)
            elif self.state == GameState.GAME_OVER:
                self.handle_game_over_events(event)
    
    def handle_user_input_events(self, event):
        """Handle user ID input events"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN and len(self.user_id_input) > 0:
                # Create session and verify sensor connections before calibration.
                self.emg_controller.create_session(self.user_id_input)
                self.emg_controller.verify_emg_connection(
                    accept_simulation=CONNECTION_CONFIG["allow_emg_simulation"]
                )
                if not self.emg_controller.ball_connection_verified:
                    self.ball_connect_in_progress = True
                    self.emg_controller.start_ensure_ball_connection_background()
                else:
                    self.emg_controller.verify_ball_connection()
                self.emg_controller._refresh_emg_connection_message()
                self.emg_controller._refresh_ball_connection_message()
                self.state = GameState.CONNECTION_VERIFY
                    
            elif event.key == pygame.K_BACKSPACE:
                self.user_id_input = self.user_id_input[:-1]
            else:
                # Add character to input
                if len(self.user_id_input) < 20 and event.unicode.isalnum():
                    self.user_id_input += event.unicode
    def handle_connection_verify_events(self, event):
        """Verify Delsys EMG and HapticBall paths before calibration."""
        if (
            event.type != pygame.KEYDOWN
            or self.ball_connect_in_progress
            or self.emg_controller.ball_connect_background_busy()
        ):
            return
        if event.key == pygame.K_e:
            self.emg_controller.reconnect_emg_path(
                accept_simulation=CONNECTION_CONFIG["allow_emg_simulation"]
            )
        elif event.key == pygame.K_c:
            self.ball_connect_in_progress = True
            self.emg_controller.start_ensure_ball_connection_background()
        elif event.key == pygame.K_r:
            self.emg_controller.reset_connection_verify_state()
        elif event.key == pygame.K_s and CONNECTION_CONFIG.get("allow_skip_connection_verify"):
            self._connection_verify_skip()
        elif event.key == pygame.K_RETURN and self.emg_controller.dual_connections_ready():
            self._advance_from_connection_verify()

    def _advance_from_connection_verify(self):
        if self.emg_controller.calibration_complete:
            self.state = GameState.USER_CHOICE
        else:
            self.state = GameState.CALIBRATION
            self.start_calibration()

    def _connection_verify_skip(self):
        """Optional bypass when config allows simulation on both paths."""
        if not CONNECTION_CONFIG.get("allow_skip_connection_verify"):
            print("Skip disabled: set CONNECTION_CONFIG['allow_skip_connection_verify']=True in config.py")
            return
        if not (
            CONNECTION_CONFIG.get("allow_emg_simulation")
            and CONNECTION_CONFIG.get("allow_ball_simulation")
        ):
            print(
                "Skip requires allow_emg_simulation and allow_ball_simulation so both paths can be coerced."
            )
            return
        print("Skipping strict verify: refreshing EMG and ball (simulation allowed)...")
        self.emg_controller.reconnect_emg_path(accept_simulation=True)
        if not self.emg_controller.emg_connection_verified:
            self.emg_controller.verify_emg_connection(accept_simulation=True)
        if not self.emg_controller.ball_connection_verified:
            self.emg_controller.ensure_ball_connection()
            self.emg_controller.verify_ball_connection()
        if self.emg_controller.dual_connections_ready():
            self._advance_from_connection_verify()
        else:
            print("Skip could not verify both paths; use E/C or adjust config.")

    def handle_user_choice_events(self, event):
        """Handle user choice events (use existing or recalibrate)"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self._advance_after_calibration()
            elif event.key == pygame.K_r:
                self.emg_controller.calibration_complete = False
                self.state = GameState.CALIBRATION
                self.start_calibration()

    def handle_calibration_events(self, event):
        """Advance from calibration summary into trigger selection."""
        if event.type != pygame.KEYDOWN or not self.emg_controller.calibration_complete:
            return
        if event.key == pygame.K_RETURN:
            self._advance_after_calibration()

    def _advance_after_calibration(self):
        """Move from calibration completion into trigger selection."""
        self.state = GameState.TRIGGER_MODE_SELECT
        modes = list(GAMEPLAY_CONTROL_CONFIG["modes"])
        if not self.emg_controller.emg_connection_verified and "keyboard" in modes:
            self.trigger_mode_index = modes.index("keyboard")
        else:
            self.trigger_mode_index = 0

    def _advance_after_trigger_mode(self):
        """Move from trigger selection into MVC percent entry."""
        self._prepare_threshold_adjust_screen()
        self.state = GameState.THRESHOLD_ADJUST
        self.threshold_adjust_enter_armed = False
        self.threshold_adjust_ready_after_ms = pygame.time.get_ticks() + 250
        pygame.event.clear(pygame.KEYDOWN)
    
    def _prepare_threshold_adjust_screen(self):
        """Initialize MVC percent entry from the latest calibration values."""
        values = self.emg_controller._normalize_calibration_peaks()
        percent_key = (
            'force_mvc_threshold_percent'
            if self.emg_controller.control_mode == 'force'
            else 'mvc_threshold_percent'
        )
        self.threshold_percent_value = float(
            values.get(
                percent_key,
                self.emg_controller.estimate_mvc_threshold_percent(values),
            )
        )
        self.threshold_percent_input = ""
        self.threshold_percent_error = ""
        self.emg_controller.apply_mvc_threshold_percent(
            self.threshold_percent_value,
            primary_mode=self.emg_controller.control_mode,
        )

    def handle_threshold_adjust_events(self, event):
        """Handle MVC percent entry and threshold adjustment events."""
        if event.type != pygame.KEYDOWN:
            return

        min_percent = CALIBRATION_CONFIG['mvc_threshold_percent_min']
        max_percent = CALIBRATION_CONFIG['mvc_threshold_percent_max']
        default_percent = CALIBRATION_CONFIG['default_mvc_threshold_percent']

        if event.key == pygame.K_RETURN:
            if self.threshold_percent_input:
                if self._apply_threshold_percent_input():
                    self.threshold_percent_input = ""
                return
            if (
                not self.threshold_adjust_enter_armed
                or pygame.time.get_ticks() < self.threshold_adjust_ready_after_ms
            ):
                return
            self.emg_controller.persist_calibration_threshold()
            self.state = GameState.MENU
        elif event.key == pygame.K_BACKSPACE:
            self.threshold_percent_input = self.threshold_percent_input[:-1]
            self.threshold_percent_error = ""
        elif event.key == pygame.K_UP:
            self._nudge_threshold_percent(1)
        elif event.key == pygame.K_DOWN:
            self._nudge_threshold_percent(-1)
        elif event.key == pygame.K_r:
            self.threshold_percent_input = ""
            self.threshold_percent_error = ""
            if self.emg_controller.apply_mvc_threshold_percent(
                default_percent,
                primary_mode=self.emg_controller.control_mode,
            ):
                self.threshold_percent_value = float(default_percent)
            else:
                self.threshold_percent_error = (
                    f"Use {min_percent}-{max_percent}% of MVC range"
                )
        elif event.unicode.isdigit() and len(self.threshold_percent_input) < 2:
            self.threshold_percent_input += event.unicode
            self.threshold_percent_error = ""

    def _apply_threshold_percent_input(self):
        """Apply typed MVC percent and refresh the live threshold."""
        if not self.threshold_percent_input:
            return False
        percent = int(self.threshold_percent_input)
        min_percent = CALIBRATION_CONFIG['mvc_threshold_percent_min']
        max_percent = CALIBRATION_CONFIG['mvc_threshold_percent_max']
        if not min_percent <= percent <= max_percent:
            self.threshold_percent_error = (
                f"Use {min_percent}-{max_percent}% of MVC range"
            )
            return False
        if self.emg_controller.apply_mvc_threshold_percent(
            percent,
            primary_mode=self.emg_controller.control_mode,
        ):
            self.threshold_percent_value = float(percent)
            self.threshold_percent_error = ""
            return True
        self.threshold_percent_error = "Could not apply MVC percent"
        return False

    def _nudge_threshold_percent(self, delta):
        """Fine-tune MVC percent with arrow keys."""
        min_percent = CALIBRATION_CONFIG['mvc_threshold_percent_min']
        max_percent = CALIBRATION_CONFIG['mvc_threshold_percent_max']
        percent = int(round(self.threshold_percent_value)) + delta
        percent = max(min_percent, min(max_percent, percent))
        self.threshold_percent_input = ""
        self.threshold_percent_error = ""
        if self.emg_controller.apply_mvc_threshold_percent(
            percent,
            primary_mode=self.emg_controller.control_mode,
        ):
            self.threshold_percent_value = float(percent)
        else:
            self.threshold_percent_error = (
                f"Use {min_percent}-{max_percent}% of MVC range"
            )
    
    def handle_trigger_mode_events(self, event):
        """Handle primary jump trigger selection."""
        if event.type != pygame.KEYDOWN:
            return
        modes = list(GAMEPLAY_CONTROL_CONFIG["modes"])
        if event.key == pygame.K_UP:
            self.trigger_mode_index = (self.trigger_mode_index - 1) % len(modes)
        elif event.key == pygame.K_DOWN:
            self.trigger_mode_index = (self.trigger_mode_index + 1) % len(modes)
        elif event.key == pygame.K_RETURN:
            selected_mode = modes[self.trigger_mode_index]
            self.emg_controller.set_control_mode(selected_mode)
            self._advance_after_trigger_mode()

    def handle_menu_events(self, event):
        """Handle menu events"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.state = GameState.PLAYING
                self.emg_controller.begin_gameplay_session()
                self.reset_game_components()
    
    def handle_game_events(self, event):
        """Handle gameplay events"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.state = GameState.GAME_OVER
            elif (
                event.key == pygame.K_SPACE
                and self.emg_controller.control_mode == "keyboard"
            ):
                if self.player.jump():
                    self.camera.cancel_auto_scroll()
                    self.emg_controller.log_jump_event("keyboard")
    
    def handle_game_over_events(self, event):
        """Handle game over events"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                # Return to menu
                self.emg_controller.stop_emg_processing()
                self.state = GameState.MENU
                self.reset_game_components()
            elif event.key == pygame.K_q:
                # Quit and save
                self.state = GameState.SESSION_END
    
    def update(self):
        """Update game state"""
        if self._prev_state is not None and self.state != self._prev_state:
            self.haptic_nav_index = self._workflow_nav_tab()
        self._prev_state = self.state

        if self.state == GameState.INITIALIZATION:
            self.update_initialization()
        elif self.state == GameState.CALIBRATION:
            self.update_calibration()
        elif self.state == GameState.CONNECTION_VERIFY:
            self.emg_controller._sync_connection_verified_from_live_io()
            if self.ball_connect_in_progress and not self.emg_controller.ball_connect_background_busy():
                self.ball_connect_in_progress = False
                self.emg_controller._refresh_emg_connection_message()
                self.emg_controller._refresh_ball_connection_message()
        elif self.state == GameState.PLAYING:
            self.update_gameplay()
        elif self.state == GameState.SESSION_END:
            self.save_and_exit()
    
    def update_initialization(self):
        """Update initialization state"""
        # Initialize EMG system
        if not self.emg_controller.python_connected:
            self.emg_controller.initialize()
        
        # Check if ready to proceed
        if self.emg_controller.python_connected:
            self.state = GameState.USER_INPUT
    
    def update_calibration(self):
        """Update calibration state"""
        feedback = self.emg_controller.consume_calibration_feedback()
        if feedback:
            self._trigger_calibration_feedback(feedback)

        if hasattr(self.emg_controller, 'calibration_system') and self.emg_controller.calibration_system:
            state = self.emg_controller.calibration_system.state
            trial = max(int(state.get('current_trial', 0)), 0)
            total = max(int(state.get('total_trials', 1)), 1)
            phase = state.get('current_phase')
            if phase in ('baseline', 'mvc') and state.get('is_collecting'):
                phase_index = 0 if phase == 'baseline' else 1
                phase_elapsed = 0.0
                if self.calibration_phase_started_at > 0:
                    phase_elapsed = min(
                        self.calibration_phase_duration,
                        time.time() - self.calibration_phase_started_at,
                    )
                self.calibration_progress = min(
                    1.0,
                    ((trial - 1) * 2 + phase_index + phase_elapsed / self.calibration_phase_duration)
                    / (total * 2),
                )
            elif state.get('active'):
                self.calibration_progress = min(1.0, trial / total)

        self._update_calibration_ball_animation()

    def _update_calibration_ball_animation(self):
        """Animate calibration balls with gravity and feedback impulses."""
        gravity = 1800.0
        dt = max(self.clock.get_time() / 1000.0, 1.0 / self.FPS)
        floor_y = float(self.calibration_bounce_floor_y)
        ceiling_y = 90.0
        for index, ball in enumerate(self.calibration_balls):
            ball["velocity"] += gravity * dt
            ball["y"] += ball["velocity"] * dt
            min_y = ceiling_y + ball["radius"]
            if ball["y"] < min_y:
                ball["y"] = min_y
                ball["velocity"] = abs(ball["velocity"]) * 0.35
            if ball["y"] >= floor_y:
                ball["y"] = floor_y
                ball["velocity"] = -abs(ball["velocity"]) * 0.45
            if abs(ball["velocity"]) < 20.0 and ball["y"] >= floor_y - 1.0:
                ball["velocity"] = -220.0 - (index * 20.0)
            ball["x"] = ball["base_x"] + math.sin(time.time() * 2.0 + index) * 4.0

    def _trigger_calibration_feedback(self, feedback):
        """Show brief on-screen jump feedback for ball squeezes and phase cues."""
        source = feedback.get('source', 'unknown')
        self.calibration_feedback_source = source
        if source == 'ball':
            force_value = feedback.get('force_value')
            if force_value is not None:
                self.calibration_feedback_label = f"Ball squeeze: {force_value:.2f}"
            else:
                self.calibration_feedback_label = "Ball squeeze detected"
            self._impulse_calibration_ball(1, 560.0)
        elif source == 'phase':
            phase = feedback.get('phase', 'phase')
            trial = feedback.get('trial')
            if trial:
                self.calibration_feedback_label = f"Phase {phase} - trial {trial}"
            else:
                self.calibration_feedback_label = f"Phase {phase}"
            self.calibration_phase_started_at = time.time()
            self.calibration_phase_duration = float(CALIBRATION_CONFIG["trial_duration"])
            self._impulse_calibration_ball(0, 420.0)
            self._impulse_calibration_ball(1, 360.0)
        else:
            self.calibration_feedback_label = feedback.get('reason', 'Calibration feedback')
            self._impulse_calibration_ball(0, 520.0)
        self.calibration_feedback_until = time.time() + 0.45

    def _impulse_calibration_ball(self, index, impulse):
        """Kick a calibration ball upward for squeeze/phase feedback."""
        if 0 <= index < len(self.calibration_balls):
            self.calibration_balls[index]["velocity"] = min(
                self.calibration_balls[index]["velocity"],
                -abs(impulse),
            )

    def update_gameplay(self):
        """Update gameplay (from original game with EMG control)"""
        dt = self.clock.get_time() / 1000.0
        
        # Check for EMG-triggered jump
        if self.emg_controller.check_jump():
            if self.player.jump():
                self.camera.cancel_auto_scroll()
        
        # Update player
        self.player.update()
        
        # Update camera
        self.camera.update(dt)
        
        # Update pipes
        for pipe in self.pipes:
            pipe.update(dt)
        
        # Check collisions
        if self.player.has_jumped_once and not self.player.is_on_pipe and not self.player.is_on_ground:
            for pipe in self.pipes:
                collision = pipe.check_collision(self.player)
                if collision == 'land':
                    self.player.land_on_pipe(pipe)
                    self.camera.auto_reposition(pipe.y)
                    if not pipe.passed:
                        self.score += 1
                        pipe.passed = True
                    break
                elif collision == 'side':
                    self.state = GameState.GAME_OVER
                    self.emg_controller.stop_emg_processing()
                    self.emg_controller.stop_ball_monitor()
                    break
        
        # Spawn new pipes
        if self.pipes:
            highest_pipe = max(pipe.y for pipe in self.pipes)
            if self.player.y + 800 > highest_pipe:
                spacing = random.randint(115, 125)
                self.pipes.append(Pipe(highest_pipe + spacing))
        
        # Remove old pipes
        self.pipes = [pipe for pipe in self.pipes if pipe.y > self.camera.y - 200]
    
    def _draw_nav_placeholder(self):
        """Material-style card when a non-workflow tab is selected (Flutter shell parity)."""
        wf = self._workflow_nav_tab()
        title = NAV_LABELS[self.haptic_nav_index]
        lines = [
            f"Live flow is on: {NAV_LABELS[wf]}.",
            "Open that tab for the EMG Jump screen; keyboard shortcuts still apply.",
            "",
            "Flutter reference: Insights → Graphs → Dashboard → Games → IMU → Settings.",
        ]
        draw_placeholder(
            self.content_surface,
            self.haptic_theme,
            title,
            lines,
            self.font,
            self.small_font,
        )

    def draw(self):
        """Draw everything"""
        theme = self.haptic_theme
        self._draw_canvas = self.content_surface
        workflow_tab = self._workflow_nav_tab()
        show_legacy = self.haptic_nav_index == workflow_tab

        self.screen.fill(theme.window_bg)

        if show_legacy:
            if self.state == GameState.PLAYING:
                self._draw_canvas.fill(fill_for_gameplay(theme))
            else:
                self._draw_canvas.fill(fill_for_shell_screen(theme))

            if self.state == GameState.INITIALIZATION:
                self.draw_initialization()
            elif self.state == GameState.USER_INPUT:
                self.draw_user_input()
            elif self.state == GameState.CONNECTION_VERIFY:
                self.draw_connection_verify()
            elif self.state == GameState.USER_CHOICE:
                self.draw_user_choice()
            elif self.state == GameState.CALIBRATION:
                self.draw_calibration()
            elif self.state == GameState.THRESHOLD_ADJUST:
                self.draw_threshold_adjust()
            elif self.state == GameState.TRIGGER_MODE_SELECT:
                self.draw_trigger_mode_select()
            elif self.state == GameState.MENU:
                self.draw_menu()
            elif self.state == GameState.PLAYING:
                self.draw_gameplay()
            elif self.state == GameState.GAME_OVER:
                self.draw_game_over()
            elif self.state == GameState.SESSION_END:
                self.draw_session_end()
        else:
            self._draw_nav_placeholder()

        draw_bottom_nav(
            self.screen,
            theme,
            self.haptic_nav_index,
            self.small_font,
            self.tiny_font,
        )
        pygame.display.flip()
    
    def draw_initialization(self):
        """Draw initialization screen"""
        # Title
        title = self.font.render("EMG Jump Game", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH//2, 100))
        self._draw_canvas.blit(title, title_rect)
        
        # Status
        y = 200
        status_lines = [
            f"Python: {'Connected' if self.emg_controller.python_connected else 'Connecting...'}",
            f"EMG: {self.emg_controller._emg_status_label()}",
            f"Ball: {self.emg_controller._ball_status_label()}",
        ]
        
        for line in status_lines:
            if "Hardware" in line:
                color = (0, 255, 0)
            elif "Simulation" in line:
                color = (255, 255, 0)
            elif "Not connected" in line:
                color = (255, 100, 100)
            else:
                color = (255, 255, 255)
            text = self.small_font.render(line, True, color)
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 40
    
    def draw_user_input(self):
        """Draw user ID input screen"""
        # Title
        title = self.font.render("Enter User ID", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH//2, 150))
        self._draw_canvas.blit(title, title_rect)
        
        # Input box
        input_box = pygame.Rect(50, 250, 300, 40)
        pygame.draw.rect(self._draw_canvas, (255, 255, 255), input_box, 2)
        
        # Input text
        input_surface = self.input_font.render(self.user_id_input, True, (255, 255, 255))
        self._draw_canvas.blit(input_surface, (input_box.x + 10, input_box.y + 5))
        
        # Instructions
        inst = self.small_font.render("Press ENTER to continue", True, (200, 200, 200))
        inst_rect = inst.get_rect(center=(self.SCREEN_WIDTH//2, 350))
        self._draw_canvas.blit(inst, inst_rect)
    
    def draw_user_choice(self):
        """Draw user choice screen"""
        # Title
        title = self.font.render("Existing Calibration Found!", True, (0, 255, 0))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH//2, 150))
        self._draw_canvas.blit(title, title_rect)
        
        # Threshold info
        threshold_text = self.small_font.render(
            f"Current Threshold: {self.emg_controller.calibration_values['threshold']:.3f}", 
            True, (255, 255, 255)
        )
        threshold_rect = threshold_text.get_rect(center=(self.SCREEN_WIDTH//2, 200))
        self._draw_canvas.blit(threshold_text, threshold_rect)
        
        # Options
        options = [
            "Press ENTER to use existing calibration",
            "Press R to recalibrate"
        ]
        
        y = 280
        for line in options:
            text = self.small_font.render(line, True, (255, 255, 255))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 40
    
    def draw_calibration(self):
        """Draw calibration screen"""
        title_surf = self.font.render("CALIBRATION", True, (255, 255, 255))
        if hasattr(self.emg_controller.calibration_system, 'state'):
            state = self.emg_controller.calibration_system.state
            phase = state.get('current_phase', 'preparation')
            trial = state.get('current_trial', 0)
            total = state.get('total_trials', 0)

            if phase == 'baseline':
                instruction = f"RELAX - Trial {trial}/{total}"
            elif phase == 'mvc':
                instruction = f"CONTRACT HARD - Trial {trial}/{total}"
            else:
                instruction = "Preparing..."
        else:
            instruction = "Initializing calibration..."

        inst_surface = self.font.render(instruction, True, (255, 255, 0))
        draw_title_card(
            self._draw_canvas,
            self.SCREEN_WIDTH // 2,
            24,
            title_surf,
            inst_surface,
        )

        bar_width = min(320, max(200, self.SCREEN_WIDTH - 48))
        bar_height = 22
        bar_x = (self.SCREEN_WIDTH - bar_width) // 2
        bar_y = 200
        draw_smooth_progress(
            self._draw_canvas,
            pygame.Rect(bar_x, bar_y, bar_width, bar_height),
            self.calibration_progress,
        )

        force_value = None
        if self.emg_controller.ball_monitor:
            force_value = self.emg_controller.ball_monitor.latest_force()
        if force_value is not None:
            force_text = self.small_font.render(
                f"Ball force: {force_value:.2f}",
                True,
                (220, 220, 220),
            )
            force_rect = force_text.get_rect(center=(self.SCREEN_WIDTH // 2, bar_y + bar_height + 22))
            self._draw_canvas.blit(force_text, force_rect)

        if self.emg_controller.calibration_complete:
            values = self.emg_controller._normalize_calibration_peaks()
            summary_lines = [
                f"EMG L baseline {values.get('baseline_left', 0.0):.3f}  peak {values.get('mvc_left_peak', values.get('mvc_left', 0.0)):.3f}",
                f"EMG R baseline {values.get('baseline_right', 0.0):.3f}  peak {values.get('mvc_right_peak', values.get('mvc_right', 0.0)):.3f}",
            ]
            if values.get('mvc_force_peak') is not None and values.get('baseline_force') is not None:
                summary_lines.append(
                    f"Ball baseline {float(values['baseline_force']):.3f}  peak {float(values['mvc_force_peak']):.3f}"
                )
            y = max(400, self.SCREEN_HEIGHT - 110)
            for line in summary_lines:
                summary_text = self.small_font.render(line, True, (180, 220, 255))
                summary_rect = summary_text.get_rect(center=(self.SCREEN_WIDTH // 2, y))
                self._draw_canvas.blit(summary_text, summary_rect)
                y += 24
            continue_text = self.small_font.render(
                "Press ENTER to choose jump trigger",
                True,
                (200, 200, 200),
            )
            continue_rect = continue_text.get_rect(center=(self.SCREEN_WIDTH // 2, y + 18))
            self._draw_canvas.blit(continue_text, continue_rect)

        feedback_active = self.calibration_feedback_until > time.time()
        floor_y = float(self.calibration_bounce_floor_y)
        ceiling_y = 90.0
        for index, ball in enumerate(self.calibration_balls):
            min_y = ceiling_y + ball["radius"]
            ball["y"] = max(min_y, min(float(ball["y"]), floor_y))
            active = feedback_active and (
                (index == 0 and self.calibration_feedback_source != 'ball')
                or (index == 1 and self.calibration_feedback_source == 'ball')
            )
            center = (int(ball["x"]), int(ball["y"]))
            kind = "ball" if str(ball.get("label", "")).lower() == "ball" else "emg"
            draw_sensor_node(
                self._draw_canvas,
                ball["label"],
                center,
                ball["radius"],
                active,
                self.small_font,
                kind=kind,
            )

        if self.calibration_feedback_label and feedback_active:
            feedback_text = self.small_font.render(
                self.calibration_feedback_label,
                True,
                (255, 255, 255),
            )
            feedback_rect = feedback_text.get_rect(center=(self.SCREEN_WIDTH // 2, 500))
            self._draw_canvas.blit(feedback_text, feedback_rect)
        elif self.calibration_feedback_source == 'ball':
            hint_text = self.small_font.render(
                "Squeeze the ball for jump feedback",
                True,
                (180, 180, 180),
            )
            hint_rect = hint_text.get_rect(center=(self.SCREEN_WIDTH // 2, 500))
            self._draw_canvas.blit(hint_text, hint_rect)
    
    def draw_threshold_adjust(self):
        """Draw MVC percent entry and threshold preview."""
        min_percent = CALIBRATION_CONFIG['mvc_threshold_percent_min']
        max_percent = CALIBRATION_CONFIG['mvc_threshold_percent_max']
        default_percent = CALIBRATION_CONFIG['default_mvc_threshold_percent']
        values = self.emg_controller._normalize_calibration_peaks()
        primary_mode = self.emg_controller.control_mode

        title = self.font.render("SET MVC THRESHOLD %", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH//2, 55))
        self._draw_canvas.blit(title, title_rect)

        mode_text = self.small_font.render(
            f"Primary trigger: {primary_mode.upper()}",
            True,
            (200, 200, 200),
        )
        mode_rect = mode_text.get_rect(center=(self.SCREEN_WIDTH//2, 88))
        self._draw_canvas.blit(mode_text, mode_rect)

        emg_lines = [
            f"EMG L baseline {values.get('baseline_left', 0.0):.3f}  peak {values.get('mvc_left_peak', values.get('mvc_left', 0.0)):.3f}",
            f"EMG R baseline {values.get('baseline_right', 0.0):.3f}  peak {values.get('mvc_right_peak', values.get('mvc_right', 0.0)):.3f}",
        ]
        y = 118
        for line in emg_lines:
            text = self.small_font.render(line, True, (180, 220, 255))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 24

        if values.get('mvc_force_peak') is not None and values.get('baseline_force') is not None:
            force_line = (
                f"Ball baseline {float(values['baseline_force']):.3f}  "
                f"peak {float(values['mvc_force_peak']):.3f}"
            )
            force_text = self.small_font.render(force_line, True, (255, 210, 150))
            force_rect = force_text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(force_text, force_rect)
            y += 28

        percent_display = (
            self.threshold_percent_input
            if self.threshold_percent_input
            else f"{int(round(self.threshold_percent_value))}"
        )
        input_box = pygame.Rect((self.SCREEN_WIDTH - 160) // 2, y, 160, 40)
        pygame.draw.rect(self._draw_canvas, (255, 255, 255), input_box, 2)
        percent_text = self.input_font.render(f"{percent_display}%", True, (255, 255, 255))
        percent_rect = percent_text.get_rect(center=input_box.center)
        self._draw_canvas.blit(percent_text, percent_rect)
        y += 58

        if primary_mode == 'force':
            current_threshold = values.get('force_threshold', BALL_CONFIG['force_threshold'])
            threshold_label = f"Ball threshold: {float(current_threshold):.3f}"
        else:
            current_threshold = values['threshold']
            threshold_label = f"EMG threshold: {current_threshold:.3f}"
        threshold_text = self.small_font.render(threshold_label, True, (255, 255, 0))
        threshold_rect = threshold_text.get_rect(center=(self.SCREEN_WIDTH//2, y))
        self._draw_canvas.blit(threshold_text, threshold_rect)
        y += 36

        instructions = [
            f"Type {min_percent}-{max_percent}, ENTER to apply",
            "UP/DOWN to fine-tune by 1%",
            "ENTER again to continue to menu",
            f"R to reset to {default_percent}%",
        ]
        for line in instructions:
            text = self.small_font.render(line, True, (200, 200, 200))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 28

        if self.threshold_percent_error:
            error_text = self.small_font.render(
                self.threshold_percent_error,
                True,
                (255, 120, 120),
            )
            error_rect = error_text.get_rect(center=(self.SCREEN_WIDTH//2, y + 10))
            self._draw_canvas.blit(error_text, error_rect)
            y += 36

        guide_text = self.small_font.render(
            "Lower % = more sensitive (easier to jump)",
            True,
            (150, 150, 150),
        )
        guide_rect = guide_text.get_rect(center=(self.SCREEN_WIDTH//2, y + 20))
        self._draw_canvas.blit(guide_text, guide_rect)

        guide_text2 = self.small_font.render(
            "Higher % = less sensitive (harder to jump)",
            True,
            (150, 150, 150),
        )
        guide_rect2 = guide_text2.get_rect(center=(self.SCREEN_WIDTH//2, y + 48))
        self._draw_canvas.blit(guide_text2, guide_rect2)
        self.threshold_adjust_enter_armed = True

    def draw_connection_verify(self):
        """Draw dual sensor connection verification."""
        emg = self.emg_controller
        live = emg.poll_connection_verify_live_samples()

        title = self.font.render("VERIFY CONNECTIONS", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH // 2, 80))
        self._draw_canvas.blit(title, title_rect)

        line_y = 118
        if emg.emg_connection_verified:
            if emg.delsys_connected:
                emg_head = "EMG: Hardware connected"
                emg_color = (120, 255, 160)
            elif emg.emg_using_simulation:
                emg_head = "EMG: Ready (non-hardware path)"
                emg_color = (255, 220, 120)
            else:
                emg_head = "EMG: Connected"
                emg_color = (180, 255, 180)
        else:
            emg_head = "EMG: Not connected"
            emg_color = (255, 120, 120)

        t_emg = self.small_font.render(emg_head, True, emg_color)
        self._draw_canvas.blit(t_emg, t_emg.get_rect(center=(self.SCREEN_WIDTH // 2, line_y)))
        line_y += 28

        # Live L/R only from real Trigno hardware (no synthetic stream on this screen).
        if live["emg_hw_lr"] is not None:
            ll, rr = live["emg_hw_lr"]
            t_live = self.small_font.render(
                f"Live EMG L={ll:.4f}   R={rr:.4f}  (hardware)",
                True,
                (220, 255, 220),
            )
            self._draw_canvas.blit(t_live, t_live.get_rect(center=(self.SCREEN_WIDTH // 2, line_y)))
            line_y += 26

        if self.ball_connect_in_progress or emg.ball_connect_background_busy():
            ball_head = "Ball: Connecting..."
            ball_color = (255, 255, 120)
        elif emg.ball_connection_verified:
            if emg.ball_hardware_connected:
                ball_head = "Ball: Hardware connected"
                ball_color = (120, 255, 160)
            elif emg.ball_using_simulation:
                ball_head = "Ball: Ready (non-hardware path)"
                ball_color = (255, 220, 120)
            else:
                ball_head = "Ball: Connected"
                ball_color = (180, 255, 180)
        else:
            ball_head = "Ball: Not connected"
            ball_color = (255, 120, 120)

        t_ball = self.small_font.render(ball_head, True, ball_color)
        self._draw_canvas.blit(t_ball, t_ball.get_rect(center=(self.SCREEN_WIDTH // 2, line_y)))
        line_y += 28

        # Live force: hardware label when BLE hardware; otherwise May12-style stream if monitor returns data.
        fv = None
        if emg.ball_monitor:
            try:
                fv = emg.ball_monitor.latest_force()
            except Exception:
                fv = None
        if live["ball_hw"] is not None:
            bf = live["ball_hw"]
            t_bf = self.small_font.render(
                f"Live force={bf:.4f}  (hardware)",
                True,
                (220, 255, 220),
            )
            self._draw_canvas.blit(t_bf, t_bf.get_rect(center=(self.SCREEN_WIDTH // 2, line_y)))
            line_y += 26
        elif fv is not None:
            hw_stream = (
                emg.ball_monitor.connection_status == "connected"
                and not emg.ball_monitor.using_simulation
            )
            tag = "(hardware)" if hw_stream else "(live stream)"
            t_bf = self.small_font.render(
                f"Live force={fv:.4f}  {tag}",
                True,
                (220, 240, 255) if hw_stream else (200, 200, 200),
            )
            self._draw_canvas.blit(t_bf, t_bf.get_rect(center=(self.SCREEN_WIDTH // 2, line_y)))
            line_y += 26

        instructions = [
            "E Re-scan / reconnect Delsys EMG + verify",
            "C Connect ball (hardware first, auto-sim if allowed)",
            "R Reset: stop fusion + ball monitor + clear verify flags",
            "ENTER Continue when both paths verified",
        ]
        if CONNECTION_CONFIG.get("allow_skip_connection_verify"):
            instructions.append(
                "S Skip verify (needs allow_emg_simulation + allow_ball_simulation)"
            )

        y = max(line_y + 22, 268)
        for line in instructions:
            text = self.small_font.render(line, True, (200, 200, 200))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH // 2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 26

    def draw_trigger_mode_select(self):
        """Draw primary jump trigger selection."""
        title = self.font.render("PRIMARY JUMP TRIGGER", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH//2, 120))
        self._draw_canvas.blit(title, title_rect)

        modes = list(GAMEPLAY_CONTROL_CONFIG["modes"])
        labels = GAMEPLAY_CONTROL_CONFIG.get("mode_labels", {})
        y = 220
        for index, mode in enumerate(modes):
            selected = index == self.trigger_mode_index
            color = (255, 255, 0) if selected else (220, 220, 220)
            prefix = "> " if selected else "  "
            text = self.small_font.render(prefix + labels.get(mode, mode), True, color)
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 40

        instructions = [
            "UP/DOWN to choose",
            "ENTER to continue",
            "Space mode when no sensor is primary",
        ]
        y = 360
        for line in instructions:
            text = self.small_font.render(line, True, (200, 200, 200))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 28
    
    def draw_menu(self):
        """Draw main menu"""
        # Title
        title = self.font.render("VERTICAL JUMP", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.SCREEN_WIDTH//2, 150))
        self._draw_canvas.blit(title, title_rect)
        
        # User info
        user_text = self.small_font.render(f"User: {self.emg_controller.user_id}", True, (200, 200, 200))
        user_rect = user_text.get_rect(center=(self.SCREEN_WIDTH//2, 200))
        self._draw_canvas.blit(user_text, user_rect)
        
        # Calibration status
        cal_status = "Calibrated" if self.emg_controller.calibration_complete else "Not Calibrated"
        cal_color = (0, 255, 0) if self.emg_controller.calibration_complete else (255, 0, 0)
        cal_text = self.small_font.render(f"Status: {cal_status}", True, cal_color)
        cal_rect = cal_text.get_rect(center=(self.SCREEN_WIDTH//2, 230))
        self._draw_canvas.blit(cal_text, cal_rect)
        
        if self.emg_controller.calibration_complete:
            thresh_text = self.small_font.render(
                f"Threshold: {self.emg_controller.calibration_values['threshold']:.2f}", 
                True, (200, 200, 200)
            )
            thresh_rect = thresh_text.get_rect(center=(self.SCREEN_WIDTH//2, 260))
            self._draw_canvas.blit(thresh_text, thresh_rect)

        mode_labels = GAMEPLAY_CONTROL_CONFIG.get("mode_labels", {})
        mode_label = mode_labels.get(self.emg_controller.control_mode, self.emg_controller.control_mode)
        mode_text = self.small_font.render(f"Trigger: {mode_label}", True, (255, 255, 255))
        mode_rect = mode_text.get_rect(center=(self.SCREEN_WIDTH//2, 300))
        self._draw_canvas.blit(mode_text, mode_rect)

        emg_status = self.emg_controller._emg_status_label()
        ball_status = self.emg_controller._ball_status_label()
        sensor_text = self.small_font.render(
            f"EMG {emg_status} | Ball {ball_status}",
            True,
            (200, 200, 200),
        )
        sensor_rect = sensor_text.get_rect(center=(self.SCREEN_WIDTH//2, 330))
        self._draw_canvas.blit(sensor_text, sensor_rect)

        jump_instruction = {
            "emg": "Contract to jump",
            "force": "Squeeze ball to jump",
            "keyboard": "Press SPACE to jump",
        }.get(self.emg_controller.control_mode, "Press SPACE to jump")
        instructions = [
            jump_instruction,
            "Non-primary sensors log passively",
            "Land on TOP of pipes",
            "",
            "Press SPACE to start",
        ]
        
        y = 380
        for line in instructions:
            text = self.small_font.render(line, True, (255, 255, 255))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 30
    
    def draw_gameplay(self):
        """Draw the fixed-resolution world (matches physics in python_pygame_version), then scale-to-fit."""
        theme = self.haptic_theme
        if self._gameplay_world_surface is None:
            self._gameplay_world_surface = pygame.Surface(
                (GAME_WORLD_WIDTH, GAME_WORLD_HEIGHT)
            )
        world = self._gameplay_world_surface
        self._layout_gameplay_dest()
        world.fill(fill_for_gameplay(theme))

        # Draw ground (world coordinates match Player / Pipe / Camera)
        if self.camera.y < 100:
            ground_y = GAME_WORLD_HEIGHT - GROUND_HEIGHT + self.camera.y
            pygame.draw.rect(world, GRASS_COLOR, (0, ground_y, GAME_WORLD_WIDTH, 20))
            pygame.draw.rect(
                world,
                GROUND_COLOR,
                (0, ground_y + 20, GAME_WORLD_WIDTH, GROUND_HEIGHT - 20),
            )

        for pipe in self.pipes:
            pipe.draw(world, self.camera.y)
        self.player.draw(world, self.camera.y)

        hud_bg = (18, 22, 32, 200)
        hud_pad = pygame.Rect(6, 6, GAME_WORLD_WIDTH - 12, 52)
        hud_surf = pygame.Surface(hud_pad.size, pygame.SRCALPHA)
        hud_surf.fill(hud_bg)
        world.blit(hud_surf, hud_pad.topleft)

        score_text = self.font.render(f"Score: {self.score}", True, (255, 215, 0))
        world.blit(score_text, (14, 12))

        mode_labels = {
            "emg": "EMG",
            "force": "Force",
            "keyboard": "Space",
        }
        mode_label = mode_labels.get(self.emg_controller.control_mode, self.emg_controller.control_mode)
        mode_text = self.small_font.render(f"Control: {mode_label}", True, (228, 232, 240))
        mode_rect = mode_text.get_rect(topright=(GAME_WORLD_WIDTH - 12, 12))
        world.blit(mode_text, mode_rect)

        emg_label = "EMG Active" if self.emg_controller.control_mode == "emg" else "EMG Logging"
        emg_color = (120, 230, 160) if self.emg_controller.control_mode == "emg" else (160, 200, 170)
        emg_text = self.small_font.render(emg_label, True, emg_color)
        emg_rect = emg_text.get_rect(topright=(GAME_WORLD_WIDTH - 12, 34))
        world.blit(emg_text, emg_rect)

        force_value = None
        if self.emg_controller.fusion_pipeline:
            with self.emg_controller.fusion_pipeline._feature_lock:
                latest_features = dict(self.emg_controller.fusion_pipeline._latest_features)
            force_value = latest_features.get("ball.force.rms")
        elif self.emg_controller.ball_monitor:
            force_value = self.emg_controller.ball_monitor.latest_force()
        if force_value is not None:
            force_label = "Force Active" if self.emg_controller.control_mode == "force" else "Force Logging"
            force_color = (255, 190, 120) if self.emg_controller.control_mode == "force" else (200, 210, 230)
            force_text = self.small_font.render(
                f"{force_label}: {force_value:.2f}",
                True,
                force_color,
            )
            force_rect = force_text.get_rect(topright=(GAME_WORLD_WIDTH - 12, 56))
            world.blit(force_text, force_rect)

        dest = self._gameplay_dest_rect
        scaled = pygame.transform.smoothscale(world, (dest.width, dest.height))
        self._draw_canvas.blit(scaled, dest.topleft)
    
    def draw_game_over(self):
        """Draw game over screen"""
        # Game Over text
        game_over = self.font.render("GAME OVER", True, (255, 255, 255))
        game_over_rect = game_over.get_rect(center=(self.SCREEN_WIDTH//2, 200))
        self._draw_canvas.blit(game_over, game_over_rect)
        
        # Score
        score_text = self.font.render(f"Score: {self.score}", True, (255, 255, 255))
        score_rect = score_text.get_rect(center=(self.SCREEN_WIDTH//2, 250))
        self._draw_canvas.blit(score_text, score_rect)
        
        # Jump count
        jump_count = len(self.emg_controller.jump_events)
        jump_text = self.small_font.render(f"Total Jumps: {jump_count}", True, (200, 200, 200))
        jump_rect = jump_text.get_rect(center=(self.SCREEN_WIDTH//2, 300))
        self._draw_canvas.blit(jump_text, jump_rect)
        
        # Options
        options = [
            "Press R to return to menu",
            "Press Q to quit and save"
        ]
        
        y = 380
        for line in options:
            text = self.small_font.render(line, True, (255, 255, 255))
            text_rect = text.get_rect(center=(self.SCREEN_WIDTH//2, y))
            self._draw_canvas.blit(text, text_rect)
            y += 30
    
    def draw_session_end(self):
        """Draw session end screen"""
        saving_text = self.font.render("Saving Data...", True, (255, 255, 255))
        saving_rect = saving_text.get_rect(center=(self.SCREEN_WIDTH//2, self.SCREEN_HEIGHT//2))
        self._draw_canvas.blit(saving_text, saving_rect)
    
    def start_calibration(self):
        """Start the calibration process"""
        self.calibration_feedback_until = 0.0
        self.calibration_feedback_label = ""
        self.calibration_feedback_source = ""
        self.calibration_phase_started_at = 0.0
        self.calibration_progress = 0.0
        for index, ball in enumerate(self.calibration_balls):
            ball["y"] = float(self.calibration_bounce_floor_y)
            ball["velocity"] = -220.0 - (index * 20.0)
            ball["x"] = ball["base_x"]
        self.emg_controller.start_calibration()
    
    def save_and_exit(self):
        """Save all data and exit"""
        self.emg_controller.stop_emg_processing()
        self.emg_controller._join_ensure_ball_background(2.0)
        self.emg_controller.stop_ball_monitor()
        self.emg_controller.save_session_data()
        time.sleep(1)  # Give time for save to complete
        self.running = False
    
    def cleanup(self):
        """Clean up resources"""
        if self.emg_controller:
            self.emg_controller.stop_emg_processing()
            self.emg_controller._join_ensure_ball_background(2.0)
            self.emg_controller.stop_ball_monitor()
            self.emg_controller.save_session_data()


# =====================================
# MAIN ENTRY POINT
# =====================================

def main():
    """Main entry point"""
    print("=" * 60)
    print("ENHANCED EMG-CONTROLLED VERTICAL JUMP GAME")
    print("Features: EMG/ball hardware or simulation, Space trigger, unified logging")
    print("=" * 60)
    
    # Create and run game
    game = IntegratedEMGGame()
    game.run()
    
    print("\nGame ended. Thank you for playing!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
