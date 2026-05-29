import asyncio
import csv
import numpy as np
from bleak import BleakError

from ball_driver import DEVICE_NAME, connect_and_stream

OUTPUT_FILE = "fsr_data.csv"

#calibration
set1_f = [1,3,4.6,5.8,6.2,7.6,8.4,9.4,13.8,15.8,20.4,23,25.2,29.2,30,32,33,35,42,45,55,63,76,78,83,97,108,114,127,134,140,159,180,184,199,238,255,269,293,315]
set1_r = [1,39,128,227,239,240,313,371,482,542,610,645,658,675,684,695,727,735,759,761,800,818,850,858,867,886,899,901,914,924,925,934,944,945,949,957,959,961,963,965]

set2_f = [0,2,4.2,5.2,6.6,10.6,13.6,31,43,46.6,62,90,152,240,252,307]
set2_r = [0,70,239,312,368,466,519,713,767,783,822,866,918,947,958,962]

set3_f = [0,4.2,12,25,32.6,45,55,58,63,71,79,89,94,162,191,210,239,243,286,293]
set3_r = [0,36,384,657,725,785,820,830,844,851,871,879,890,929,940,946,952,954,960,962]

reference_grid = np.arange(0, 1024, 1)

interp_set1 = np.interp(reference_grid, set1_r, set1_f)
interp_set2 = np.interp(reference_grid, set2_r, set2_f)
interp_set3 = np.interp(reference_grid, set3_r, set3_f)

master_force_table = (interp_set1 + interp_set2 + interp_set3) / 3.0

def raw_to_newtons(raw_val: float) -> float:
    """Clamps incoming values to safe bounds and maps them using the master calibration data table."""
    # Ensure raw values fall within bounds of 10-bit resolution array indexing
    idx = int(clip(raw_val, 0, 1023))
    return float(master_force_table[idx])

def clip(val, min_val, max_val):
    return max(min_val, min(val, max_val))

async def main():
    with open(OUTPUT_FILE, "w", newline="") as handle:
        csv.writer(handle).writerow(["timestamp_ms", "fsr_raw", "force_newtons"])

    def on_sample(timestamp_ms: float, fsr_raw: float) -> None:
        force_n = raw_to_newtons(fsr_raw)
        
        print(f"[{timestamp_ms:08.0f} ms] Raw ADC: {int(fsr_raw):4d} -> Force: {force_n:6.2f} N")
        
        with open(OUTPUT_FILE, "a", newline="") as handle:
            csv.writer(handle).writerow([timestamp_ms, int(fsr_raw), round(force_n, 3)])

    try:
        while True:
            print(f"Scanning for '{DEVICE_NAME}'...")
            await connect_and_stream(on_sample=on_sample)
            await asyncio.sleep(1.0)
    except BleakError as exc:
        print(f"BLE error: {exc}")
    except KeyboardInterrupt:
        pass
    print("\nData session ended. Saved all samples to:", OUTPUT_FILE)


if __name__ == "__main__":
    asyncio.run(main())

# import asyncio
# import csv

# from bleak import BleakError

# from ball_driver import DEVICE_NAME, connect_and_stream

# OUTPUT_FILE = "fsr_data.csv"


# async def main():
#     with open(OUTPUT_FILE, "w", newline="") as handle:
#         csv.writer(handle).writerow(["timestamp_ms", "fsr_raw"])

#     def on_sample(timestamp_ms: float, force: float) -> None:
#         with open(OUTPUT_FILE, "a", newline="") as handle:
#             csv.writer(handle).writerow([timestamp_ms, force])

#     try:
#         while True:
#             print(f"Scanning for '{DEVICE_NAME}'...")
#             await connect_and_stream(on_sample=on_sample)
#             await asyncio.sleep(1.0)
#     except BleakError as exc:
#         print(f"BLE error: {exc}")
#     except KeyboardInterrupt:
#         pass
#     print("Data saved to", OUTPUT_FILE)


# if __name__ == "__main__":
#     asyncio.run(main())


