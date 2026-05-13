#!/usr/bin/env python3
"""
Enhanced Delsys Interface with Hardware Timestamp Support
Captures both Python time and Delsys hardware time for synchronization
"""

import time
import numpy as np
from collections import deque

class DelsysInterface:
    def __init__(self):
        self.is_connected = False
        self.simulation_mode = True
        self.last_update = time.time()
        
        # Hardware timestamp tracking
        self.hardware_start_time = None
        self.python_start_time = None
        self.time_offset = 0.0  # Offset between hardware and Python time
        
        # Buffer for timestamp synchronization
        self.timestamp_buffer = deque(maxlen=100)
        
        print("DelsysInterface initialized with timestamp support")
        
    @property
    def is_hardware_connected(self):
        """True when live Delsys hardware is streaming."""
        return self.is_connected and not self.simulation_mode

    def initialize(self):
        """Initialize Delsys connection with timestamp synchronization.

        Returns True only when hardware connects; simulation fallbacks return False.
        FUSION ADDITION: session verification is owned by the game controller.
        """
        try:
            # Try to import AeroPy for real hardware
            from pythonnet import load
            load("coreclr")
            import clr
            clr.AddReference("resources/DelsysAPI")
            from Aero import AeroPy
            
            self.aeropy = AeroPy()
            
            # Initialize channel storage
            self.channel_guids = []
            self.all_scanned_sensors = []
            AEROPY_KEY = "MIIBKjCB4wYHKoZIzj0CATCB1wIBATAsBgcqhkjOPQEBAiEA/////wAAAAEAAAAAAAAAAAAAAAD///////////////8wWwQg/////wAAAAEAAAAAAAAAAAAAAAD///////////////wEIFrGNdiqOpPns+u9VXaYhrxlHQawzFOw9jvOPD4n0mBLAxUAxJ02CIbnBJNqZnjhE50mt4GffpAEIQNrF9Hy4SxCR/i85uVjpEDydwN9gS3rM6D0oTlF2JjClgIhAP////8AAAAA//////////+85vqtpxeehPO5ysL8YyVRAgEBA0IABGQniQ0Kus6FXXkBHgTMMyK7YMduVcEfTtGl3/GffyqhF80FZD6LNPjAxr7qvX8DkTl4gFktFoHPygHB94atwU4="
            AEROPY_LICENSE = "<License>  <Id>421ad755-a1f2-45a8-879e-3d1293bb7649</Id>  <Type>Trial</Type>  <Quantity>10</Quantity>  <LicenseAttributes>    <Attribute name='Software'></Attribute>  </LicenseAttributes>  <ProductFeatures>    <Feature name='Sales'>True</Feature>    <Feature name='Billing'>False</Feature>  </ProductFeatures>  <Customer>    <Name>University of Oxford</Name>    <Email>liang.he@eng.ox.ac.uk</Email>  </Customer>  <Expiration>Sun, 04 Mar 2035 00:00:00 GMT</Expiration>  <Signature>MEUCIQDDwwEhfHGrcHJBLGUyDd7jLGroheO9F+reTQ9l3qrIwQIgMLVnTDHRlYQCa5Vw50dxFiaa/lVFIJ3EBnOxsEeIci0=</Signature></License>"
            self.aeropy.ValidateBase(AEROPY_KEY, AEROPY_LICENSE)

            
            # Scan for sensors
            print("Scanning for Delsys sensors...")
            scan_result = self.aeropy.ScanSensors().Result
            self.all_scanned_sensors = self.aeropy.GetScannedSensorsFound()
            
            sensor_count = 0
            for sensor in self.all_scanned_sensors:
                print(f"({sensor.PairNumber}) {sensor.FriendlyName}")
                self.aeropy.SelectSensor(sensor_count)
                sensor_count += 1
            
            if sensor_count > 0:
                # Configure the pipeline
                self.aeropy.Configure(False, False)
                
                if self.aeropy.IsPipelineConfigured():
                    # Map channels
                    for i in range(sensor_count):
                        sensor = self.aeropy.GetSensorObject(i)
                        print(f"Sensor {i+1}: {sensor.FriendlyName}")
                        
                        for channel in sensor.TrignoChannels:
                            if str(channel.Type) != "SkinCheck":
                                ch_guid = str(channel.Id)
                                ch_type = str(channel.Type)
                                ch_name = str(channel.Name)
                                sample_rate = round(channel.SampleRate, 3)
                                
                                self.channel_guids.append(ch_guid)
                                print(f"  {ch_name} ({ch_type}, {sample_rate} Hz): {ch_guid}")
                    
                    # Start data collection and record start times
                    print("Starting data collection with timestamp sync...")
                    self.python_start_time = time.time()
                    self.aeropy.Start()
                    
                    # Get initial hardware timestamp if available
                    self._initialize_hardware_timestamp()
                    
                    # Wait for data flow
                    time.sleep(0.5)
                    
                    # Get initial EMG reading
                    initial_data = self._get_real_emg_with_timestamp()
                    print(f"Initial EMG: L={initial_data['left']:.4f}, R={initial_data['right']:.4f}")
                    print(f"Timestamp sync: Python={initial_data['python_time']:.6f}, Hardware={initial_data['hardware_time']:.6f}")
                    
                    self.is_connected = True
                    self.simulation_mode = False
                    print(f"✅ Delsys initialized with {sensor_count} sensors and timestamp sync")
                    return True
            
            # No sensors found
            print("No Delsys sensors found, using simulation with synthetic timestamps")
            self.simulation_mode = True
            self.is_connected = False
            self._initialize_simulation_timestamps()
            return False
            
        except Exception as e:
            print(f"Delsys hardware not available, using simulation: {e}")
            self.simulation_mode = True
            self.is_connected = False
            self._initialize_simulation_timestamps()
            return False
    
    def _initialize_hardware_timestamp(self):
        """Initialize hardware timestamp synchronization"""
        try:
            if hasattr(self.aeropy, 'GetSystemTime'):
                # Get hardware system time if available
                self.hardware_start_time = self.aeropy.GetSystemTime()
            else:
                # Use Python time as fallback
                self.hardware_start_time = self.python_start_time
            
            # Calculate initial offset
            self.time_offset = self.hardware_start_time - self.python_start_time
            
            print(f"Hardware timestamp initialized: offset={self.time_offset:.6f}s")
            
        except Exception as e:
            print(f"Could not get hardware timestamp, using Python time: {e}")
            self.hardware_start_time = self.python_start_time
            self.time_offset = 0.0
    
    def _initialize_simulation_timestamps(self):
        """Initialize timestamps for simulation mode"""
        self.python_start_time = time.time()
        self.hardware_start_time = self.python_start_time
        self.time_offset = 0.0  # No offset in simulation
        print("Simulation timestamps initialized")
    
    def get_emg_data_with_timestamps(self):
        """Get EMG data with both Python and hardware timestamps"""
        if self.simulation_mode:
            return self._simulate_emg_with_timestamps()
        else:
            return self._get_real_emg_with_timestamp()
    
    def get_emg_data(self):
        """Legacy method - returns EMG data in original format"""
        data = self.get_emg_data_with_timestamps()
        return (data['left'], data['right'], 
                data['acc1_x'], data['acc1_y'], data['acc1_z'],
                data['acc2_x'], data['acc2_y'], data['acc2_z'])
    
    def get_hardware_timestamp(self):
        """Get current hardware timestamp"""
        if self.simulation_mode:
            # In simulation, use Python time with synthetic offset
            return time.time() + self.time_offset
        else:
            try:
                if hasattr(self.aeropy, 'GetSystemTime'):
                    return self.aeropy.GetSystemTime()
                else:
                    # Estimate hardware time based on offset
                    return time.time() + self.time_offset
            except:
                return time.time() + self.time_offset
    
    def _simulate_emg_with_timestamps(self):
        """Simulate EMG data with timestamps"""
        python_time = time.time()
        hardware_time = python_time + self.time_offset  # Simulated hardware time
        
        # Generate EMG signals
        t = python_time
        left = abs(np.sin(t * 2)) * 0.1 + np.random.normal(0, 0.02)
        right = abs(np.cos(t * 2)) * 0.1 + np.random.normal(0, 0.02)
        
        # Add occasional bursts
        if np.random.random() < 0.05:
            left += np.random.uniform(0.2, 0.8)
        if np.random.random() < 0.05:
            right += np.random.uniform(0.2, 0.8)
        
        # Simulate accelerometer
        acc1_x = np.sin(t * 0.5) * 0.1 + np.random.normal(0, 0.01)
        acc1_y = np.cos(t * 0.7) * 0.1 + np.random.normal(0, 0.01)
        acc1_z = 0.9 + np.random.normal(0, 0.02)
        
        acc2_x = np.sin(t * 0.6 + 1.0) * 0.1 + np.random.normal(0, 0.01)
        acc2_y = np.cos(t * 0.8 + 1.5) * 0.1 + np.random.normal(0, 0.01)
        acc2_z = 0.9 + np.random.normal(0, 0.02)
        
        return {
            'python_time': python_time,
            'hardware_time': hardware_time,
            'time_offset': self.time_offset,
            'left': left,
            'right': right,
            'acc1_x': acc1_x, 'acc1_y': acc1_y, 'acc1_z': acc1_z,
            'acc2_x': acc2_x, 'acc2_y': acc2_y, 'acc2_z': acc2_z,
            'sample_index': int((python_time - self.python_start_time) * 2000)  # Sample index at 2000Hz
        }
    
    def _get_real_emg_with_timestamp(self):
        """Get real EMG data with hardware timestamps"""
        python_time = time.time()
        hardware_time = self.get_hardware_timestamp()
        
        try:
            dataReady = self.aeropy.CheckDataQueue()
            if dataReady:
                DataOut = self.aeropy.PollData()
                
                # Extract timestamp if available in the data packet
                packet_timestamp = None
                if hasattr(DataOut, 'Timestamp'):
                    packet_timestamp = DataOut.Timestamp
                elif hasattr(DataOut, 'SystemTime'):
                    packet_timestamp = DataOut.SystemTime
                
                # Use packet timestamp if available, otherwise use current hardware time
                if packet_timestamp is not None:
                    hardware_time = packet_timestamp
                
                # Extract EMG and accelerometer data (same as before)
                emg1 = emg2 = 0.0
                acc1_x = acc1_y = acc1_z = 0.0
                acc2_x = acc2_y = acc2_z = 0.0
                
                # Extract EMG and accelerometer data using channel GUIDs
                emg1_guid = None
                emg2_guid = None
                acc_channels = {'sensor1': {'x': None, 'y': None, 'z': None}, 
                               'sensor2': {'x': None, 'y': None, 'z': None}}

                # Identify channel types from the stored channel_guids and sensor objects
                if hasattr(self, 'channel_guids') and hasattr(self, 'all_scanned_sensors'):
                    emg_sensor_count = 0
                    
                    # Map channel GUIDs to their types by checking sensor objects in discovery order
                    for discovery_idx, sensor in enumerate(self.all_scanned_sensors):
                        sensor_key = f'sensor{discovery_idx + 1}'  # sensor1, sensor2, etc.
                        
                        for channel in sensor.TrignoChannels:
                            ch_guid = str(channel.Id)
                            ch_type = str(channel.Type)
                            ch_name = str(channel.Name)
                            
                            if ch_guid in self.channel_guids:
                                if ch_type == 'EMG':
                                    emg_sensor_count += 1
                                    if emg1_guid is None:
                                        emg1_guid = ch_guid
                                    elif emg2_guid is None:
                                        emg2_guid = ch_guid
                                elif ch_type == 'Accelerometer':
                                    # Use more specific pattern matching for accelerometer axes
                                    if 'ACC X' in ch_name:
                                        acc_channels[sensor_key]['x'] = ch_guid
                                    elif 'ACC Y' in ch_name:
                                        acc_channels[sensor_key]['y'] = ch_guid
                                    elif 'ACC Z' in ch_name:
                                        acc_channels[sensor_key]['z'] = ch_guid
                else:
                    # Fallback: assume first two channels are EMG
                    if hasattr(self, 'channel_guids') and len(self.channel_guids) >= 2:
                        emg1_guid = self.channel_guids[0]
                        emg2_guid = self.channel_guids[1]
                    elif hasattr(self, 'channel_guids') and len(self.channel_guids) >= 1:
                        emg1_guid = self.channel_guids[0]
                        emg2_guid = None

                # Extract EMG values using official DataManager.py pattern
                if emg1_guid is not None:
                    try:
                        # Official Delsys API: Convert string to .NET GUID for dictionary access
                        from System import Guid
                        guid_obj = Guid.Parse(emg1_guid)
                        if guid_obj in DataOut:  # Check if GUID exists in current DataOut
                            chan_data_1 = DataOut[guid_obj]  # Official API pattern
                            emg1_data = list(chan_data_1)     # Convert .NET List to Python list
                            emg1 = emg1_data[-1] if emg1_data else 0.0
                        else:
                            # GUID not found in current DataOut batch
                            emg1 = 0.0
                    except Exception as e:
                        print(f"Error reading EMG1 data: {e}")
                        emg1 = 0.0
                else:
                    emg1 = 0.0
                        
                if emg2_guid is not None:
                    try:
                        # Official Delsys API: Convert string to .NET GUID for dictionary access
                        from System import Guid
                        guid_obj = Guid.Parse(emg2_guid)
                        if guid_obj in DataOut:  # Check if GUID exists in current DataOut
                            chan_data_2 = DataOut[guid_obj]  # Official API pattern
                            emg2_data = list(chan_data_2)     # Convert .NET List to Python list
                            emg2 = emg2_data[-1] if emg2_data else 0.0
                        else:
                            # GUID not found in current DataOut batch
                            emg2 = 0.0
                    except Exception as e:
                        print(f"Error reading EMG2 data: {e}")
                        emg2 = 0.0
                else:
                    emg2 = 0.0
                
                # Extract accelerometer values using the SAME poll method (official API)
                # Sensor 1 accelerometer data
                for axis, guid in acc_channels['sensor1'].items():
                    if guid is not None:
                        try:
                            # Official Delsys API: Convert string to .NET GUID for dictionary access
                            from System import Guid
                            guid_obj = Guid.Parse(guid)
                            if guid_obj in DataOut:  # Check if GUID exists in current DataOut
                                acc_data = list(DataOut[guid_obj])  # Official API pattern
                                acc_value = acc_data[-1] if acc_data else 0.0
                                if axis == 'x':
                                    acc1_x = acc_value
                                elif axis == 'y':
                                    acc1_y = acc_value
                                elif axis == 'z':
                                    acc1_z = acc_value
                            # else: GUID not found, keep default 0.0 value
                        except Exception as e:
                            print(f"Error reading Sensor 1 ACC {axis.upper()} data: {e}")
                
                # Sensor 2 accelerometer data
                for axis, guid in acc_channels['sensor2'].items():
                    if guid is not None:
                        try:
                            # Official Delsys API: Convert string to .NET GUID for dictionary access
                            from System import Guid
                            guid_obj = Guid.Parse(guid)
                            if guid_obj in DataOut:  # Check if GUID exists in current DataOut
                                acc_data = list(DataOut[guid_obj])  # Official API pattern
                                acc_value = acc_data[-1] if acc_data else 0.0
                                if axis == 'x':
                                    acc2_x = acc_value
                                elif axis == 'y':
                                    acc2_y = acc_value
                                elif axis == 'z':
                                    acc2_z = acc_value
                            # else: GUID not found, keep default 0.0 value
                        except Exception as e:
                            print(f"Error reading Sensor 2 ACC {axis.upper()} data: {e}")
                
                # Calculate sample index based on elapsed time
                elapsed_time = python_time - self.python_start_time
                sample_index = int(elapsed_time * 2000)  # 2000Hz sampling
                
                # Update timestamp synchronization buffer
                self.timestamp_buffer.append({
                    'python': python_time,
                    'hardware': hardware_time,
                    'offset': hardware_time - python_time
                })
                
                # Periodically recalculate offset for drift compensation
                if len(self.timestamp_buffer) >= 50:
                    offsets = [ts['offset'] for ts in self.timestamp_buffer]
                    self.time_offset = np.median(offsets)  # Use median for robustness
                
                return {
                    'python_time': python_time,
                    'hardware_time': hardware_time,
                    'time_offset': self.time_offset,
                    'left': emg1,
                    'right': emg2,
                    'acc1_x': acc1_x, 'acc1_y': acc1_y, 'acc1_z': acc1_z,
                    'acc2_x': acc2_x, 'acc2_y': acc2_y, 'acc2_z': acc2_z,
                    'sample_index': sample_index,
                    'packet_timestamp': packet_timestamp  # Original packet timestamp if available
                }
            
            # No data ready, return zeros with current timestamps
            return {
                'python_time': python_time,
                'hardware_time': hardware_time,
                'time_offset': self.time_offset,
                'left': 0.0, 'right': 0.0,
                'acc1_x': 0.0, 'acc1_y': 0.0, 'acc1_z': 0.0,
                'acc2_x': 0.0, 'acc2_y': 0.0, 'acc2_z': 0.0,
                'sample_index': int((python_time - self.python_start_time) * 2000)
            }
            
        except Exception as e:
            print(f"Error getting hardware timestamps: {e}")
            # Fallback to simulation-style timestamps
            return self._simulate_emg_with_timestamps()
    
    def get_timestamp_statistics(self):
        """Get statistics about timestamp synchronization"""
        if not self.timestamp_buffer:
            return {
                'offset_mean': 0.0,
                'offset_std': 0.0,
                'drift_rate': 0.0,
                'samples': 0
            }
        
        offsets = [ts['offset'] for ts in self.timestamp_buffer]
        
        # Calculate drift rate if we have enough samples
        drift_rate = 0.0
        if len(self.timestamp_buffer) >= 10:
            early_offset = np.mean(offsets[:10])
            late_offset = np.mean(offsets[-10:])
            time_span = self.timestamp_buffer[-1]['python'] - self.timestamp_buffer[0]['python']
            if time_span > 0:
                drift_rate = (late_offset - early_offset) / time_span
        
        return {
            'offset_mean': np.mean(offsets),
            'offset_std': np.std(offsets),
            'drift_rate': drift_rate,  # seconds drift per second
            'samples': len(self.timestamp_buffer),
            'current_offset': self.time_offset
        }
    
    def calibrate_timestamps(self, duration=5.0):
        """Calibrate timestamp synchronization over a period"""
        print(f"Calibrating timestamps for {duration} seconds...")
        
        calibration_data = []
        start_time = time.time()
        
        while time.time() - start_time < duration:
            data = self.get_emg_data_with_timestamps()
            calibration_data.append({
                'python': data['python_time'],
                'hardware': data['hardware_time'],
                'offset': data['hardware_time'] - data['python_time']
            })
            time.sleep(0.001)  # Sample at 1kHz for calibration
        
        # Calculate robust offset estimate
        offsets = [d['offset'] for d in calibration_data]
        self.time_offset = np.median(offsets)
        
        print(f"Timestamp calibration complete:")
        print(f"  Offset: {self.time_offset:.6f}s")
        print(f"  Std Dev: {np.std(offsets):.6f}s")
        print(f"  Samples: {len(calibration_data)}")
        
        return self.time_offset
