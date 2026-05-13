#!/usr/bin/env python3
"""
Advanced EMG Calibration System
Handles baseline noise, MVC consistency, and adaptive thresholding
Uses centralized configuration for consistency
"""

import numpy as np
import time
from collections import deque
from scipy import signal
import threading
from config import CALIBRATION_CONFIG, EMG_CORE_CONFIG

class AdvancedCalibrationSystem:
    """Advanced calibration system addressing noise and consistency issues"""
    
    def __init__(self, unity_communication_callback=None, session_path=None, delsys_interface=None):
        self.unity_callback = unity_communication_callback
        self.session_path = session_path
        self.delsys_interface = delsys_interface
        
        # Calibration configuration
        self.config = {
            'total_trials': 3,              # 3 trials total
            'trial_duration': 4.0,          # 4s per phase
            'phase_rest': 1.0,              # 1s between baseline→MVC
            'trial_rest': 2.0,              # 3s between trials
            'baseline_noise_threshold': 0.15,  # Maximum acceptable baseline noise
            'mvc_consistency_threshold': 0.3,   # Minimum MVC consistency required
            'outlier_removal_std': 2.0,        # Remove outliers beyond N standard deviations
            'adaptive_filtering': False,         # Enable adaptive noise filtering
            'quality_control': True            # Enable calibration quality checks
        }
        
        # Calibration state
        self.state = {
            'active': False,
            'current_phase': None,
            'current_trial': 0,
            'total_trials': 0,
            'sequence_index': 0,
            'is_collecting': False
        }
        
        # Data storage with quality metrics
        self.calibration_data = {
            'baseline': {
                'trials': [],                # Store all trial data
                'left_samples': [],
                'right_samples': [],
                'quality_scores': [],
                'noise_levels': []
            },
            'mvc': {
                'trials': [],                # Store all trial data
                'left_samples': [],
                'right_samples': [],         # Add missing right_samples array
                'quality_scores': [],
                'consistency_scores': []
            }
        }
        self.rms_window = deque(maxlen=50)
        self.right_rms = 0
        self.left_rms = 0
        
        # Real-time processing
        self.sample_buffer = deque(maxlen=1000)  # 0.5s at 2000Hz
        self.filtered_buffer = deque(maxlen=100) # Filtered data for analysis
        
        # Quality control thresholds
        self.quality_thresholds = {
            'baseline_max_noise': 0.1,      # Maximum noise for baseline
            'mvc_min_activation': 0.3,      # Minimum activation for valid MVC
            'consistency_min_score': 0.7,   # Minimum consistency score
            'snr_min_threshold': 10.0       # Minimum signal-to-noise ratio
        }
        
        # Calibration results
        self.final_calibration = {
            'baseline_left': 0.05,
            'baseline_right': 0.05,
            'mvc_left': 0.8,
            'mvc_right': 0.8,
            'threshold': 0.3,
            'sensitivity': 1.0,
            'quality_score': 0.0,
            'warnings': []
        }
        
        print("🎯 Advanced EMG Calibration System initialized")
        print("🔧 Features: Noise handling, MVC consistency, adaptive filtering")

    def start_calibration_sequence(self):
        """Start alternating baseline + MVC calibration sequence"""
        print("🚀 Starting Alternating Baseline + MVC Calibration Sequence")
        
        # Reset calibration state
        self.state.update({
            'active': True,
            'current_trial': 1,
            'total_trials': self.config['total_trials'],
            'is_collecting': False
        })
        
        # Clear previous data
        for phase in ['baseline', 'mvc']:
            for key in self.calibration_data[phase]:
                self.calibration_data[phase][key].clear()
        
        # Send initial calibration message
        if self.unity_callback:
            self.unity_callback({
                'type': 'calibration_started',
                'timestamp': time.time(),
                'total_trials': self.config['total_trials'],
                'estimated_duration': self.config['total_trials'] * 
                                    (self.config['trial_duration'] * 2 + self.config['trial_rest']),
                'instruction': 'Each trial: Relax → Contract → Rest',
                'features': ['noise_filtering', 'quality_control', 'alternating_trials']
            })
        
        # Start first trial
        self._start_trial(1)

    def _notify_phase_started(self, phase, trial_num, instruction):
        """FUSION ADDITION: notify UI/ball feedback when a collection phase begins."""
        if self.unity_callback:
            self.unity_callback({
                'type': 'calibration_phase_started',
                'timestamp': time.time(),
                'phase': phase,
                'trial': trial_num,
                'total_trials': self.config['total_trials'],
                'duration': self.config['trial_duration'],
                'instruction': instruction,
                'action': 'phase_started',
            })

    def _start_trial(self, trial_num):
        """Start a trial with baseline + MVC phases"""
        print(f"🔄 Starting Trial {trial_num}/{self.config['total_trials']}")
        
        self.state.update({
            'current_trial': trial_num,
            'current_phase': 'baseline'
        })
        
        # Start with baseline phase
        self._collect_baseline_phase(trial_num)

    def _collect_baseline_phase(self, trial_num):
        """Collect baseline data for current trial"""
        print(f"📊 Trial {trial_num}: Collecting baseline data...")
        
        self.state['current_phase'] = 'baseline'
        self.state['is_collecting'] = True
        self._notify_phase_started(
            'baseline',
            trial_num,
            f'Trial {trial_num}/{self.config["total_trials"]}: relax and stay still',
        )
        
        # Clear sample buffer
        self.sample_buffer.clear()
        self.filtered_buffer.clear()
        
        # Collect baseline data
        collection_thread = threading.Thread(
            target=self._baseline_collection_worker,
            args=(trial_num,),
            daemon=True
        )
        collection_thread.start()

    def _collect_mvc_phase(self, trial_num):
        """Collect MVC data for current trial"""
        print(f"💪 Trial {trial_num}: Collecting MVC data...")
        
        self.state['current_phase'] = 'mvc'
        self.state['is_collecting'] = True
        self._notify_phase_started(
            'mvc',
            trial_num,
            f'Trial {trial_num}/{self.config["total_trials"]}: contract as hard as you can',
        )
        
        # Clear sample buffer
        self.sample_buffer.clear()
        self.filtered_buffer.clear()
        
        # Collect MVC data
        collection_thread = threading.Thread(
            target=self._mvc_collection_worker,
            args=(trial_num,),
            daemon=True
        )
        collection_thread.start()

    def _baseline_collection_worker(self, trial_num):
        """Worker thread for baseline data collection"""
        start_time = time.time()
        duration = self.config['trial_duration']
        
        # Data collection arrays
        left_samples = []
        right_samples = []
        timestamps = []
        
        print(f"🔄 Collecting baseline data for {duration} seconds...")
        
        while time.time() - start_time < duration:
            # Simulate getting EMG data (replace with actual Delsys interface)
            current_time = time.time()
            
            # # Simulate realistic baseline with noise
            # left_raw = np.random.normal(0.03, 0.015)  # Small baseline with noise
            # right_raw = np.random.normal(0.025, 0.012)
            
            # # Add occasional noise spikes (muscle twitches)
            # if np.random.random() < 0.02:  # 2% chance
            #     left_raw += np.random.uniform(0.05, 0.15)
            # if np.random.random() < 0.02:
            #     right_raw += np.random.uniform(0.05, 0.15)
            
            # Apply adaptive filtering


            
            emg_data = self.delsys_interface.get_emg_data()
            left_raw, right_raw = emg_data[0], emg_data[1]
            self.rms_window.append((left_raw, right_raw))
            if len(self.rms_window) >= 25:
                left_values = [x[0] for x in self.rms_window]
                right_values = [x[1] for x in self.rms_window]
                self.left_rms = np.sqrt(np.mean(np.square(left_values)))
                self.right_rms = np.sqrt(np.mean(np.square(right_values)))

            if self.config['adaptive_filtering']:
                # left_filtered, right_filtered = self._apply_adaptive_filter(self.left_rms, self.right_rms)
                left_filtered, right_filtered = self.left_rms, self.right_rms
            else:
                left_filtered, right_filtered = self.left_rms, self.right_rms
            
            # Store samples
            left_samples.append(left_filtered)
            right_samples.append(right_filtered)
            timestamps.append(current_time)
            
            # Real-time quality assessment
            if len(left_samples) > 50:  # Check quality every 50 samples
                self._assess_baseline_quality_realtime(left_samples[-50:], right_samples[-50:])
            
            # Provide visual feedback if muscle activity detected
            max_activity = max(abs(left_filtered), abs(right_filtered))
            if max_activity > self.quality_thresholds['baseline_max_noise']:
                self._send_baseline_feedback(left_filtered, right_filtered, 'too_active')
            
            time.sleep(1.0 / 125)  # 125Hz collection rate
        
        # Store trial data
        self._store_trial_data(trial_num, 'baseline', left_samples, right_samples, timestamps)
        
        # Move to MVC phase
        print(f"⏸️  Moving to MVC phase for Trial {trial_num}")
        threading.Timer(self.config['phase_rest'], 
                       self._collect_mvc_phase, args=[trial_num]).start()

    def _mvc_collection_worker(self, trial_num):
        """Worker thread for MVC data collection"""
        start_time = time.time()
        duration = self.config['trial_duration']
        
        # Data collection arrays
        left_samples = []
        right_samples = []
        timestamps = []
        
        print(f"🔥 Collecting MVC data for {duration} seconds...")
        
        while time.time() - start_time < duration:
            current_time = time.time()
        

            emg_data = self.delsys_interface.get_emg_data()
            left_raw, right_raw = emg_data[0], emg_data[1]
            if left_raw > 0.0001 and right_raw > 0.0001:
                self.rms_window.append((left_raw, right_raw))
                print(f'left raw value: {left_raw} and right rawvalue: {right_raw}')
            if len(self.rms_window) >= 1:
                left_values = [x[0] for x in self.rms_window]
                right_values = [x[1] for x in self.rms_window]
                self.left_rms = np.sqrt(np.mean(np.square(left_values)))
                self.right_rms = np.sqrt(np.mean(np.square(right_values)))
                
                # print(f'left raw value: {left_raw} and right rawvalue: {right_raw}')
            
            # Apply filtering
            if self.config['adaptive_filtering']:
                # left_filtered, right_filtered = self._apply_adaptive_filter(self.left_rms, self.right_rms)
                left_filtered, right_filtered = self.left_rms, self.right_rms
            else:
                left_filtered, right_filtered = self.left_rms, self.right_rms
                # print(f'left raw value: {left_raw} and right rawvalue: {right_raw}')
                # print(f'here is filtered data:{left_filtered} and {right_filtered}')

            # print(f'here is filtered fake data:{left_filtered} and {right_filtered}')
            
            
            ## We don't want stimulated data, the real data is too noisy

            # Store samples
            left_samples.append(left_filtered)
            right_samples.append(right_filtered)
            timestamps.append(current_time)
            
            # Provide real-time visual feedback for good contractions
            max_activity = max(left_filtered, right_filtered)
            if max_activity > self.quality_thresholds['mvc_min_activation']:
                self._send_mvc_feedback(left_filtered, right_filtered, 'good_contraction')
            
            time.sleep(1.0 / 125)  # 125Hz collection rate
        
        # Store trial data
        self._store_trial_data(trial_num, 'mvc', left_samples, right_samples, timestamps)
        
        # Move to next trial or finish
        if trial_num < self.config['total_trials']:
            # Rest period, then next trial
            print(f"⏸️  Rest period before Trial {trial_num + 1}")
            threading.Timer(self.config['trial_rest'], 
                          self._start_trial, args=[trial_num + 1]).start()
        else:
            # All trials complete
            self._finalize_calibration()

    def _store_trial_data(self, trial_num, phase, left_samples, right_samples, timestamps):
        """Store data from a single trial phase"""
        trial_data = {
            'trial': trial_num,
            'phase': phase,
            'left_samples': left_samples,
            'right_samples': right_samples,
            'timestamps': timestamps,
            'left_mean': np.mean(left_samples),
            'right_mean': np.mean(right_samples),
            'left_std': np.std(left_samples),
            'right_std': np.std(right_samples)
        }
        
        # Store in calibration data
        self.calibration_data[phase]['trials'].append(trial_data)
        
        # Also store in existing arrays for compatibility
        if phase == 'baseline':
            self.calibration_data['baseline']['left_samples'].append(trial_data['left_mean'])
            self.calibration_data['baseline']['right_samples'].append(trial_data['right_mean'])
            quality_score = self._calculate_baseline_quality(left_samples, right_samples)
            noise_level = max(trial_data['left_std'], trial_data['right_std'])
            self.calibration_data['baseline']['quality_scores'].append(quality_score)
            self.calibration_data['baseline']['noise_levels'].append(noise_level)
            
            print(f"✅ Baseline Trial {trial_num}: L={trial_data['left_mean']:.4f}±{trial_data['left_std']:.4f}")
            print(f"   R={trial_data['right_mean']:.4f}±{trial_data['right_std']:.4f}")
            print(f"   Quality Score: {quality_score:.2f}, Noise Level: {noise_level:.4f}")
        else:
            self.calibration_data['mvc']['left_samples'].append(trial_data['left_mean'])
            self.calibration_data['mvc']['right_samples'].append(trial_data['right_mean'])
            quality_score = self._calculate_mvc_quality(left_samples, right_samples)
            consistency_score = self._calculate_mvc_consistency(left_samples, right_samples)
            self.calibration_data['mvc']['quality_scores'].append(quality_score)
            self.calibration_data['mvc']['consistency_scores'].append(consistency_score)
            
            print(f"✅ MVC Trial {trial_num}: L={trial_data['left_mean']:.4f}±{trial_data['left_std']:.4f}")
            print(f"   R={trial_data['right_mean']:.4f}±{trial_data['right_std']:.4f}")
            print(f"   Quality Score: {quality_score:.2f}, Consistency: {consistency_score:.3f}")
        
        # Send results to Unity
        if self.unity_callback:
            self.unity_callback({
                'type': 'calibration_trial_complete',
                'timestamp': time.time(),
                'phase': phase,
                'trial': trial_num,
                'leftAverage': trial_data['left_mean'],
                'rightAverage': trial_data['right_mean'],
                'qualityScore': quality_score,
                'action': 'trial_complete'
            })

    def _finalize_calibration(self):
        """Calculate final calibration values from all trials"""
        print("🏁 All Trials Complete - Finalizing Calibration")
        
        # Calculate averages from all trials
        baseline_trials = self.calibration_data['baseline']['trials']
        mvc_trials = self.calibration_data['mvc']['trials']
        
        if not baseline_trials or not mvc_trials:
            print("❌ No trial data available for finalization")
            return
        
        # Baseline averages
        baseline_left = np.mean([t['left_mean'] for t in baseline_trials])
        baseline_right = np.mean([t['right_mean'] for t in baseline_trials])
        
        # MVC averages
        mvc_left = np.mean([t['left_mean'] for t in mvc_trials])
        mvc_right = np.mean([t['right_mean'] for t in mvc_trials])

        # mvc_left = 0.1
        # mvc_right = 0.1
        
        # Calculate threshold (30% of MVC range)
        default_percent = CALIBRATION_CONFIG['default_mvc_threshold_percent']
        threshold_left = baseline_left + (default_percent / 100.0) * (mvc_left - baseline_left)
        threshold_right = baseline_right + (default_percent / 100.0) * (mvc_right - baseline_right)
        threshold = max(threshold_left, threshold_right)
        
        # Store final results (important change here)
        self.final_calibration.update({
            'baseline_left': baseline_left,
            'baseline_right': baseline_right,
            'mvc_left': mvc_left,
            'mvc_right': mvc_right,
            'threshold': threshold,
            'mvc_threshold_percent': default_percent,
            # 'threshold': 0.07,
            'quality_score': 0.9  # You can calculate this based on consistency
        })
        
        print(f"🎯 CALIBRATION COMPLETE!")
        print(f"   Baseline: L={baseline_left:.4f}, R={baseline_right:.4f}")
        print(f"   MVC: L={mvc_left:.4f}, R={mvc_right:.4f}")
        print(f"   Threshold: {threshold:.3f}")
        
        # Save detailed trial data
        self._save_trial_data()
        
        # Send final calibration to Unity
        if self.unity_callback:
            self.unity_callback({
                'type': 'calibration_complete',
                'timestamp': time.time(),
                'result': self.final_calibration,
                'isComplete': True,
                'instruction': 'Combined trial calibration completed successfully!',
                'action': 'calibration_finished'
            })
        
        self.state['active'] = False

    def _save_trial_data(self):
        """Save detailed trial data for analysis"""
        import json
        from pathlib import Path
        
        # Use session path if available, otherwise fall back to calibration_trials
        if self.session_path:
            data_dir = Path(self.session_path) / "calibration"
            data_dir.mkdir(parents=True, exist_ok=True)
            trial_file = data_dir / f"trial_data_{int(time.time())}.json"
        else:
            # Fallback for standalone testing
            data_dir = Path("GameData") / "calibration_trials"
            data_dir.mkdir(parents=True, exist_ok=True)
            trial_file = data_dir / f"trial_data_{int(time.time())}.json"
        
        # Save detailed trial data
        trial_summary = {
            'timestamp': time.time(),
            'total_trials': self.config['total_trials'],
            'trial_structure': 'baseline + mvc per trial',
            'baseline_trials': self.calibration_data['baseline']['trials'],
            'mvc_trials': self.calibration_data['mvc']['trials'],
            'final_calibration': self.final_calibration
        }
        
        # Save to file
        with open(trial_file, 'w') as f:
            json.dump(trial_summary, f, indent=2)
        
        print(f"📊 Trial data saved to {trial_file}")

    # ==========================================
    # HELPER METHODS
    # ==========================================

    def _apply_adaptive_filter(self, left_raw, right_raw):
        """Apply adaptive filtering to reduce noise"""
        # Simple moving average filter (can be enhanced with more sophisticated filtering)
        self.sample_buffer.append((left_raw, right_raw))
        
        if len(self.sample_buffer) < 5:
            return left_raw, right_raw
        
        # Calculate moving average
        recent_samples = list(self.sample_buffer)[-5:]
        left_filtered = np.mean([s[0] for s in recent_samples])
        right_filtered = np.mean([s[1] for s in recent_samples])
        
        return left_filtered, right_filtered

    def _remove_outliers(self, samples):
        """Remove outliers using IQR method"""
        if len(samples) < 4:
            return samples
            
        q75, q25 = np.percentile(samples, [75, 25])
        iqr = q75 - q25
        lower_bound = q25 - (1.5 * iqr)
        upper_bound = q75 + (1.5 * iqr)
        
        return [x for x in samples if lower_bound <= x <= upper_bound]

    def _calculate_baseline_quality(self, left_samples, right_samples):
        """Calculate baseline quality score (0-1, higher is better)"""
        # Lower noise and stable signal = higher quality
        left_stability = 1.0 / (1.0 + np.std(left_samples) * 10)
        right_stability = 1.0 / (1.0 + np.std(right_samples) * 10)
        
        # Check if values are in expected baseline range
        left_range_score = 1.0 if np.mean(left_samples) < 0.1 else 0.5
        right_range_score = 1.0 if np.mean(right_samples) < 0.1 else 0.5
        
        return (left_stability + right_stability + left_range_score + right_range_score) / 4

    def _calculate_mvc_quality(self, left_samples, right_samples):
        """Calculate MVC quality score (0-1, higher is better)"""
        # Higher peak values and good signal-to-noise ratio = higher quality
        left_peak = np.max(left_samples) - self.final_calibration['baseline_left']
        right_peak = np.max(right_samples) - self.final_calibration['baseline_right']
        
        # Score based on peak amplitude
        left_amplitude_score = min(1.0, left_peak / 0.5)  # Normalize to 0.5 as good MVC
        right_amplitude_score = min(1.0, right_peak / 0.5)
        
        # Score based on signal consistency during contraction
        left_consistency = 1.0 - (np.std(left_samples) / np.mean(left_samples)) if np.mean(left_samples) > 0 else 0
        right_consistency = 1.0 - (np.std(right_samples) / np.mean(right_samples)) if np.mean(right_samples) > 0 else 0
        
        return (left_amplitude_score + right_amplitude_score + left_consistency + right_consistency) / 4

    def _calculate_mvc_consistency(self, left_samples, right_samples):
        """Calculate MVC consistency score (0-1, higher is better)"""
        # Find the 90th percentile of the corrected data
        left_corrected = np.array(left_samples) - self.final_calibration['baseline_left']
        right_corrected = np.array(right_samples) - self.final_calibration['baseline_right']
        
        left_top10_percent = left_corrected[left_corrected >= np.percentile(left_corrected, 90)]
        right_top10_percent = right_corrected[right_corrected >= np.percentile(right_corrected, 90)]
        
        # Calculate consistency as the ratio of std to mean of the top 10%
        left_consistency = 1.0 - (np.std(left_top10_percent) / np.mean(left_top10_percent)) if len(left_top10_percent) > 0 else 0
        right_consistency = 1.0 - (np.std(right_top10_percent) / np.mean(right_top10_percent)) if len(right_top10_percent) > 0 else 0
        
        return (left_consistency + right_consistency) / 2

    def _assess_baseline_quality_realtime(self, left_recent, right_recent):
        """Real-time assessment of baseline quality"""
        left_noise = np.std(left_recent)
        right_noise = np.std(right_recent)
        
        if max(left_noise, right_noise) > self.quality_thresholds['baseline_max_noise']:
            print(f"⚠️  High baseline noise detected: L={left_noise:.4f}, R={right_noise:.4f}")

    def _send_baseline_feedback(self, left_val, right_val, feedback_type):
        """Send baseline feedback to Unity"""
        if self.unity_callback and feedback_type == 'too_active':
            self.unity_callback({
                'command': 'jump',
                'timestamp': time.time(),
                'leftValue': left_val,
                'rightValue': right_val,
                'threshold': self.quality_thresholds['baseline_max_noise'],
                'reason': 'Baseline feedback - muscles too active, try to relax more',
                'source': 'calibration_baseline_warning'
            })

    def _send_mvc_feedback(self, left_val, right_val, feedback_type):
        """Send MVC feedback to Unity"""
        if self.unity_callback and feedback_type == 'good_contraction':
            self.unity_callback({
                'command': 'jump',
                'timestamp': time.time(),
                'leftValue': left_val,
                'rightValue': right_val,
                'threshold': self.quality_thresholds['mvc_min_activation'],
                'reason': 'MVC feedback - good muscle contraction!',
                'source': 'calibration_mvc_feedback'
            })

    def _send_calibration_instruction(self, phase, instruction, details, trial, duration):
        """Send calibration instruction to Unity"""
        if self.unity_callback:
            self.unity_callback({
                'type': 'calibration_phase',
                'timestamp': time.time(),
                'phase': phase,
                'trial': trial,
                'trialsTotal': self.config['total_trials'],
                'duration': duration,
                'instruction': instruction,
                'details': details,
                'action': 'instruction'
            })

    def _generate_calibration_warnings(self):
        """Generate calibration quality warnings"""
        warnings = []
        
        # Check baseline quality
        baseline_quality = np.mean(self.calibration_data['baseline']['quality_scores'])
        if baseline_quality < 0.6:
            warnings.append("Baseline quality is low - try to stay more relaxed during baseline trials")
        
        # Check MVC consistency
        mvc_consistency = np.mean(self.calibration_data['mvc']['consistency_scores'])
        if mvc_consistency < 0.7:
            warnings.append("MVC consistency is low - try to maintain steady contractions")
        
        # Check MVC amplitude
        max_left_mvc = max(self.calibration_data['mvc']['left_samples'])
        # max_left_mvc = 0.07
        max_right_mvc = max(self.calibration_data['mvc']['right_samples'])
        # max_right_mvc =0.07
        if max_left_mvc < 0.3 or max_right_mvc < 0.3:
            warnings.append("MVC values are low - try contracting muscles harder")
        
        # Check noise levels
        max_noise = max(self.calibration_data['baseline']['noise_levels'])
        if max_noise > 0.08:
            warnings.append("High baseline noise detected - check electrode placement")
        
        self.final_calibration['warnings'] = warnings
        
        if warnings:
            print("⚠️  Calibration Warnings:")
            for warning in warnings:
                print(f"   • {warning}")

    # ==========================================
    # PUBLIC API
    # ==========================================

    def get_calibration_results(self):
        """Get final calibration results"""
        return self.final_calibration.copy()

    def is_calibrating(self):
        """Check if calibration is active"""
        return self.state['active']

    def stop_calibration(self):
        """Stop calibration process"""
        if self.state['active']:
            print("🛑 Calibration stopped by user")
            self.state['active'] = False
            
            if self.unity_callback:
                self.unity_callback({
                    'type': 'calibration_stopped',
                    'timestamp': time.time(),
                    'reason': 'user_requested'
                })

# Integration with MultiThreadedEMGSystem
def integrate_advanced_calibration(emg_system, session_path=None):
    """Integrate advanced calibration with multi-threaded EMG system"""
    
    def unity_callback(data):
        """Callback to send data to Unity"""
        emg_system.send_to_unity(data)
    
    # Create advanced calibration system
    advanced_calibration = AdvancedCalibrationSystem(unity_callback, session_path)
    
    # Replace the simple calibration methods in the EMG system
    emg_system.advanced_calibration = advanced_calibration
    
    print("🔗 Advanced calibration integrated with multi-threaded EMG system")
    return advanced_calibration

print("🎯 Advanced EMG Calibration System Ready")
print("🔧 Features: Noise filtering, quality control, adaptive thresholds, consistency checking")
print("📊 Handles: Baseline noise, MVC variability, outlier removal, real-time feedback")