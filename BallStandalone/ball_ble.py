import asyncio
import csv

from bleak import BleakError

from ball_driver import DEVICE_NAME, connect_and_stream

OUTPUT_FILE = "fsr_data.csv"


async def main():
    with open(OUTPUT_FILE, "w", newline="") as handle:
        csv.writer(handle).writerow(["timestamp_ms", "fsr_raw"])

    def on_sample(timestamp_ms: float, force: float) -> None:
        with open(OUTPUT_FILE, "a", newline="") as handle:
            csv.writer(handle).writerow([timestamp_ms, force])

    try:
        while True:
            print(f"Scanning for '{DEVICE_NAME}'...")
            await connect_and_stream(on_sample=on_sample)
            await asyncio.sleep(1.0)
    except BleakError as exc:
        print(f"BLE error: {exc}")
    except KeyboardInterrupt:
        pass
    print("Data saved to", OUTPUT_FILE)


if __name__ == "__main__":
    asyncio.run(main())
