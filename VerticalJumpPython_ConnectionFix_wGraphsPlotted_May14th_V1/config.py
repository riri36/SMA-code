#!/usr/bin/env python3
"""
Configuration file for Multi-Threaded EMG Gaming System
All system parameters and settings
"""

# =====================================
# THREAD CONFIGURATION
# =====================================

THREAD_RATES = {
    'raw_collection': 1000,     # Hz - Delsys hardware sampling rate
    'game_processing': 200,     # Hz - Fast game response processing
    'user_analysis': 50,        # Hz - Behavioral analysis
    'data_logging': 60,         # Hz - Synchronized data logging
    'unity_communication': 120  # Hz - High refresh visual feedback
}

THREAD_PRIORITIES = {
    'raw_collection': 'high',
    'game_processing': 'above_normal',
    'user_analysis': 'normal',
    'data_logging': 'normal',
    'unity_communication': 'above_normal'
}

# =====================================
# BUFFER CONFIGURATION
# =====================================

BUFFER_SIZES = {
    'raw_data_buffer': 4000,        # 2 seconds at 2000Hz
    'processed_buffer': 400,        # 2 seconds at 200Hz
    'analysis_buffer': 100,         # 2 seconds at 50Hz
    'unity_command_queue': 1000,    # Unity command buffer
    'logging_queue': 20000          # Data logging buffer
}

# =====================================
# PERFORMANCE TARGETS
# =====================================

PERFORMANCE_TARGETS = {
    'target_latency_ms': 25,        # 25ms end-to-end target
    'max_acceptable_latency_ms': 50, # Warning threshold
    'jump_cooldown_ms': 150,        # Minimum time between jumps
    'priority_queue_limit': 50,     # Max priority messages per Unity frame
    'buffer_warning_threshold': 0.8 # Warn when buffers >80% full
}

# =====================================
# UNITY COMMUNICATION
# =====================================

UNITY_CONFIG = {
    'host': '127.0.0.1',
    'send_port': 12346,        # Port to send data to Unity
    'receive_port': 12345,     # Port to receive data from Unity
    'connection_timeout': 5.0,  # Connection timeout in seconds
    'heartbeat_interval': 2.0,  # Heartbeat ping interval
    'max_message_size': 65536   # Maximum UDP message size
}

# =====================================
# CALIBRATION CONFIGURATION
# =====================================

CALIBRATION_CONFIG = {
    # Trial configuration
    'baseline_trials': 3,
    'mvc_trials': 3,
    'trial_duration': 4.0,      # Seconds per trial
    'rest_duration': 3.0,       # Seconds between trials
    'countdown_duration': 3.0,   # Countdown before each trial
    
    # Quality control thresholds
    'baseline_noise_threshold': 0.15,    # Max acceptable baseline noise
    'mvc_consistency_threshold': 0.3,    # Min MVC consistency required
    'outlier_removal_std': 2.0,          # Remove outliers beyond N std devs
    'quality_score_threshold': 0.6,      # Min quality score for acceptance
    
    # Signal processing
    'adaptive_filtering': True,
    'quality_control': True,
    'real_time_feedback': True,
    
    # Adaptive thresholding
    'base_threshold': 0.3,               # 30% of MVC range
    'max_threshold_adjustment': 0.1,     # Max adjustment based on noise
    'sensitivity_default': 1.0,
    'mvc_threshold_percent_min': 10,     # Minimum MVC-range percent entry
    'mvc_threshold_percent_max': 80,     # Maximum MVC-range percent entry
    'default_mvc_threshold_percent': 30, # Default MVC-range percent after calibration
}

# =====================================
# EMG PROCESSING - CENTRALIZED CONFIGURATION
# =====================================

# Core EMG Processing Parameters (used by all components)
EMG_CORE_CONFIG = {
    # Data Collection Rates
    'raw_collection_rate': 2000,    # Hz - Hardware raw data rate
    'calibration_rate': 2000,       # Hz - Calibration data collection rate  
    'gameplay_rate': 200,           # Hz - Gameplay processing rate
    
    # RMS Processing (consistent across all components)
    'rms_window_size': 25,          # Samples for RMS calculation
    'rms_overlap': 0.5,             # Window overlap (0.0 to 1.0)
    'rms_calculation_rate': 60,     # Hz - RMS calculation rate
    
    # Data Storage Format
    'data_format': {
        'timestamp': 'unity_timestamp',
        'local_timestamp': 'local_timestamp', 
        'emg1_raw': 'emg1',
        'emg2_raw': 'emg2',
        'emg1_rms': 'rms1',
        'emg2_rms': 'rms2'
    }
}

# Legacy EMG Processing (for backward compatibility)
EMG_PROCESSING = {
    # RMS calculation
    'rms_window_size': EMG_CORE_CONFIG['rms_window_size'],
    'rms_overlap': EMG_CORE_CONFIG['rms_overlap'],
    
    # Jump detection
    'jump_hysteresis': 0.08,    # Threshold hysteresis
    'anti_oscillation_window': 10, # Samples to check for oscillation
    'oscillation_threshold': 3,  # Max oscillations before suppression
    
    # Default calibration values (before calibration)
    'default_baseline_left': 0.05,
    'default_baseline_right': 0.05,
    'default_mvc_left': 0.8,
    'default_mvc_right': 0.8,
    'default_threshold': 0.3
}

# =====================================
# DATA LOGGING
# =====================================

DATA_LOGGING = {
    'base_directory': 'GameData',
    'save_interval': 5.0,           # Auto-save interval in seconds
    'batch_size': 50,               # Records per batch write
    'file_formats': ['csv', 'jsonl'], # Supported formats
    'compression': False,           # Enable compression
    'max_file_size_mb': 100,       # Max file size before rotation
    
    # Data types to log
    'log_raw_emg': True,
    'log_processed_emg': True,
    'log_events': True,
    'log_calibration': True,
    'log_performance': True,
    'auto_plot_session': True,
    # Spawn `plot_session_interactive.py` in a subprocess at session save (non-blocking; skipped headless).
    'interactive_plot_on_session_end': True,
    # If True, skip headless heuristics (SDL dummy / DISPLAY) so the plot subprocess still runs — for local
    # debugging only; CI is never overridden. See docs/INTERACTIVE_PLOTS.md.
    'interactive_plot_force': True,
}

# =====================================
# HARDWARE CONFIGURATION
# =====================================

DELSYS_CONFIG = {
    'auto_initialize': True,
    'number_of_sensors': 2,
    'sampling_rate': 2000,
    'use_simulation_fallback': True,  # Use simulation if hardware fails
    'connection_retry_attempts': 3,
    'connection_retry_delay': 2.0,
    
    # Simulation parameters (when hardware unavailable)
    'simulation_noise_level': 0.02,
    'simulation_activation_probability': 0.02,
    'simulation_activation_strength': (0.3, 1.2)
}

# FUSION ADDITION: HapticBall force sensing and gameplay control defaults.
BALL_CONFIG = {
    'device_name': 'HapticBall',
    # Bleak WinRT: connect includes GATT service discovery; default can TimeoutError on slow/busy stacks.
    'bleak_connect_timeout_s': 60.0,
    # If True, Bleak attempts pairing before connect (try if GATT times out on a new PC).
    'bleak_pair_before_connect': False,
    # >0: try hardware ball connect (no sim fallback) for up to this many seconds
    # before Delsys/pythonnet starts. 0 = skip (probe only, then Delsys as today).
    'early_ball_init_max_s': 60,
    'scan_timeout_s': 10.0,
    'connection_verify_timeout_s': 12.0,
    'poll_hz': 60.0,
    # FUSION ADDITION: BLE/sim samples arrive near ~20 Hz; fusion resamples to master_hz.
    'native_sample_hz': 20.0,
    'force_threshold': 0.35,
    'force_arm_above': 0.35,
    'force_disarm_below': 0.15,
    'refractory_ms': PERFORMANCE_TARGETS['jump_cooldown_ms'],
    'simulate_when_absent': True,
    'queue_size': 1000,
    'keep_duration': 1.0,
    # FUSION ADDITION: squeeze feedback during calibration collection phases.
    'calibration_feedback_threshold': 0.35,
    'calibration_feedback_arm_above': 0.35,
    'calibration_feedback_disarm_below': 0.15,
    'calibration_feedback_refractory_ms': 500.0,
    # FUSION ADDITION: console debug for simulated HapticBall force ('auto', True, False).
    'print_simulated_force': 'auto',
    'print_simulated_force_every_n': 20,
    'print_simulated_force_min_delta': 0.08,
    'print_simulated_force_interval_s': 1.0,
     # True: throttled prints for real BLE notifications in the console ([HapticBall HW]).
    'print_ball_hardware_samples': True,
    'print_ball_hardware_interval_s': 0.25,
    'print_ball_hardware_min_delta': 0.01,
}


def should_print_ball_simulated_force(
    simulating: bool,
    *,
    monitoring_active: bool = False,
) -> bool:
    """Return whether simulated ball force should be echoed to the console."""
    if not simulating:
        return False
    # FUSION ADDITION: auto prints only during active calibration/gameplay monitoring.
    setting = BALL_CONFIG.get('print_simulated_force', 'auto')
    if setting is True:
        return True
    if setting is False:
        return False
    return monitoring_active

GAMEPLAY_CONTROL_CONFIG = {
    'default_mode': 'emg',
    'modes': ('emg', 'force', 'keyboard'),
    'passive_emg_logging': True,
    'passive_ball_logging': True,
    'mode_labels': {
        'emg': 'EMG primary (hardware or simulation)',
        'force': 'Ball primary (hardware or simulation)',
        'keyboard': 'Space bar (no sensor primary)',
    },
}

CONNECTION_CONFIG = {
    'require_emg_path': True,
    'require_ball_path': True,
    'allow_emg_simulation': DELSYS_CONFIG['use_simulation_fallback'],
    'allow_ball_simulation': BALL_CONFIG['simulate_when_absent'],
    # When True, CONNECTION_VERIFY accepts **S** to coerce simulation paths (if allowed) and continue.
    'allow_skip_connection_verify': False,
}

# FUSION ADDITION: gameplay fusion bus and trigger defaults.
FUSION_CONFIG = {
    # FUSION ADDITION: fusion bus timing is owned here (not EMG_CORE_CONFIG).
    'master_hz': 200,
    'delay_s': 0.03,
    'window_s': 1.0,
    # FUSION ADDITION: ball_force resampled on the shared fusion bus.
    'sensors': ['flexor', 'extensor', 'ball_force'],
    'left_sensor': 'flexor',
    'right_sensor': 'extensor',
    'ball_sensor': 'ball_force',
    'delsys_sensor_map': {
        'flexor': 14,
        'extensor': 10,
    },
    'rms_window': 16,
    'ball_rms_window': 4,
    # FUSION ADDITION: force jump trigger uses ball.force.rms when True, else fused ball.force.
    'ball_trigger_use_rms': True,
    'simulate_delsys': DELSYS_CONFIG['use_simulation_fallback'],
    'simulate_ball': BALL_CONFIG['simulate_when_absent'],
    'ball_device_name': BALL_CONFIG['device_name'],
    'jump_triggers': {
        'emg': {
            'id': 'jump',
            'source': 'emg.rms.flexor',
            'threshold': EMG_PROCESSING['default_threshold'],
            'arm_above': EMG_PROCESSING['default_threshold'],
            'disarm_below': EMG_PROCESSING['default_threshold'] * 0.55,
            'refractory_ms': PERFORMANCE_TARGETS['jump_cooldown_ms'],
        },
        'force': {
            'id': 'force_jump',
            'source': 'ball.force.rms',
            'threshold': BALL_CONFIG['force_threshold'],
            'arm_above': BALL_CONFIG['force_arm_above'],
            'disarm_below': BALL_CONFIG['force_disarm_below'],
            'refractory_ms': BALL_CONFIG['refractory_ms'],
        },
    },
    # FUSION ADDITION: legacy single-trigger alias for EMG gameplay.
    'jump_trigger': {
        'id': 'jump',
        'source': 'emg.rms.flexor',
        'threshold': EMG_PROCESSING['default_threshold'],
        'arm_above': EMG_PROCESSING['default_threshold'],
        'disarm_below': EMG_PROCESSING['default_threshold'] * 0.55,
        'refractory_ms': PERFORMANCE_TARGETS['jump_cooldown_ms'],
    },
}

# =====================================
# SYSTEM MONITORING
# =====================================

MONITORING_CONFIG = {
    'enable_performance_monitoring': True,
    'health_check_interval': 10.0,    # System health check frequency
    'log_performance_stats': True,
    'performance_history_length': 100, # Number of samples to keep
    'warning_thresholds': {
        'high_cpu_usage': 80.0,        # CPU usage %
        'high_memory_usage': 80.0,     # Memory usage %
        'high_latency_ms': 50.0,       # Latency warning
        'low_fps': 50.0                # Frame rate warning
    }
}

# =====================================
# DEBUG AND DEVELOPMENT
# =====================================

DEBUG_CONFIG = {
    'enable_debug_logging': True,
    'verbose_thread_logging': False,
    'log_all_messages': False,
    'save_debug_data': True,
    'enable_profiling': False,
    'profile_output_file': 'performance_profile.prof'
}

# =====================================
# USER INTERFACE
# =====================================

UI_CONFIG = {
    'show_performance_overlay': True,
    'show_calibration_progress': True,
    'show_emg_values': True,
    'update_frequency_hz': 30,         # UI update rate
    'chart_history_seconds': 10.0,     # EMG chart history
    'auto_hide_debug_info': False
}

# =====================================
# VALIDATION FUNCTIONS
# =====================================

def validate_config():
    """Validate configuration settings"""
    errors = []
    
    # Check thread rates are reasonable
    if THREAD_RATES['game_processing'] > THREAD_RATES['raw_collection']:
        errors.append("Game processing rate cannot exceed raw collection rate")
    
    # Check buffer sizes are adequate
    min_buffer = THREAD_RATES['raw_collection'] * 0.5  # 0.5 second minimum
    if BUFFER_SIZES['raw_data_buffer'] < min_buffer:
        errors.append(f"Raw data buffer too small, minimum: {min_buffer}")
    
    # Check latency targets are achievable
    min_possible_latency = 1000 / THREAD_RATES['game_processing']
    if PERFORMANCE_TARGETS['target_latency_ms'] < min_possible_latency:
        errors.append(f"Target latency unrealistic, minimum: {min_possible_latency:.1f}ms")
    
    # Check calibration durations
    if CALIBRATION_CONFIG['trial_duration'] < 2.0:
        errors.append("Calibration trial duration too short, minimum 2.0 seconds")
    
    return errors

def print_config_summary():
    """Print configuration summary"""
    print("🔧 EMG Gaming System Configuration")
    print("=" * 50)
    print(f"📡 Raw Collection: {THREAD_RATES['raw_collection']}Hz")
    print(f"🎮 Game Processing: {THREAD_RATES['game_processing']}Hz") 
    print(f"🎨 Unity Communication: {THREAD_RATES['unity_communication']}Hz")
    print(f"🎯 Target Latency: {PERFORMANCE_TARGETS['target_latency_ms']}ms")
    print(f"📊 Calibration: {CALIBRATION_CONFIG['baseline_trials']}B + {CALIBRATION_CONFIG['mvc_trials']}M trials")
    print(f"💾 Data Logging: {DATA_LOGGING['save_interval']}s intervals")
    print(f"🔗 Unity: {UNITY_CONFIG['host']}:{UNITY_CONFIG['send_port']}")
    print("=" * 50)

# Validate configuration on import
_config_errors = validate_config()
if _config_errors:
    print("⚠️ Configuration Errors:")
    for error in _config_errors:
        print(f"   • {error}")
    print("Please fix configuration errors before running the system.")
else:
    print("✅ Configuration validated successfully")

if __name__ == "__main__":
    print_config_summary()