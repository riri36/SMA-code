from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEVICE_NAME = "HapticBall"

FSR_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"


async def connect_and_stream(
    *,
    device_name: str = DEVICE_NAME,
    on_sample: Optional[Callable[[float, float], None]] = None,
    scan_timeout: float = 10.0,
) -> None:
    from bleak import BleakClient, BleakScanner

    device = await BleakScanner.find_device_by_name(device_name, timeout=scan_timeout)
    if device is None:
        logger.warning("Device '%s' not found", device_name)
        return
        
    async with BleakClient(device) as client:

        def notification_handler(_sender, data: bytearray) -> None:
            try:
                line = data.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError:
                return
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 2:
                return
            try:
                timestamp_ms = float(parts[0])
                force = float(parts[1])
            except ValueError:
                return
            if on_sample:
                on_sample(timestamp_ms, force)

        await client.start_notify(FSR_CHAR_UUID, notification_handler)
        
        while client.is_connected:
            await asyncio.sleep(0.05)
                    
        await client.stop_notify(FSR_CHAR_UUID)

# from __future__ import annotations

# import asyncio
# import logging
# from typing import Callable, Optional

# logger = logging.getLogger(__name__)

# DEVICE_NAME = "HapticBall"
# # FSR_CHAR_UUID = "00002a56-0000-1000-8000-00805f9b34fb"
# # CMD_CHAR_UUID = "00002a57-0000-1000-8000-00805f9b34fb"

# FSR_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
# CMD_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef0"


# async def send_command(client, cmd: str) -> None:
#     await client.write_gatt_char(CMD_CHAR_UUID, cmd.encode("utf-8"), response=True)


# async def connect_and_stream(
#     *,
#     device_name: str = DEVICE_NAME,
#     on_sample: Optional[Callable[[float, float], None]] = None,
#     scan_timeout: float = 10.0,
# ) -> None:
#     from bleak import BleakClient, BleakScanner

#     device = await BleakScanner.find_device_by_name(device_name, timeout=scan_timeout)
#     if device is None:
#         logger.warning("Device '%s' not found", device_name)
#         return
#     async with BleakClient(device) as client:
#         await send_command(client, "SYNC")

#         def notification_handler(_sender, data: bytearray) -> None:
#             try:
#                 line = data.decode("utf-8", errors="strict").strip()
#             except UnicodeDecodeError:
#                 return
#             parts = [part.strip() for part in line.split(",")]
#             if len(parts) != 2:
#                 return
#             try:
#                 timestamp_ms = float(parts[0])
#                 force = float(parts[1])
#             except ValueError:
#                 return
#             if on_sample:
#                 on_sample(timestamp_ms, force)

#         await client.start_notify(FSR_CHAR_UUID, notification_handler)
#         while client.is_connected:
#             await asyncio.sleep(0.05)
#         try:
#             await send_command(client, "SLEEP")
#         except Exception:
#             pass
#         await client.stop_notify(FSR_CHAR_UUID)
