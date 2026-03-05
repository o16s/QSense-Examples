#!/usr/bin/env python3
"""
stream_example.py — Stream 9DOF IMU data from a QSense sensor over BLE.

Run on a Raspberry Pi (CM4 or similar with Bluetooth):

    python stream_example.py                      # 10 s at default rate
    python stream_example.py --duration 30        # 30 s
    python stream_example.py --rate 200           # 200 Hz with per-sample timestamps

No dongle required — connects directly via Bluetooth Low Energy.
"""

import argparse
import asyncio

from qsense_ble import QSenseBleClient


async def main(duration: float, rate: float | None) -> None:
    client = QSenseBleClient(sampling_rate=rate)

    # 1. Scan
    print("Scanning for QSense sensors …")
    devices = await client.scan(timeout=5.0)
    if not devices:
        print("No QSense sensor found. Make sure the sensor is powered on and nearby.")
        return
    print(f"Found: {devices[0].name} ({devices[0].address})")

    # 2. Connect
    print("Connecting …")
    await client.connect()
    print("Connected.")

    # 3. Stream
    rate_info = f" at {rate} Hz" if rate else ""
    print(f"Streaming for {duration} seconds{rate_info} (Ctrl+C to stop early) …\n")
    try:
        async for frame in client.stream(duration=duration):
            header = frame["header"]
            for i, sample in enumerate(frame["samples"]):
                # Use per-sample timestamp when available, else header timestamp
                ts = sample.get("timestamp", header.timestamp)
                values = "  ".join(
                    f"{k}={v:+.4f}"
                    for k, v in sample.items()
                    if k != "timestamp"
                )
                print(f"[{ts:%H:%M:%S.%f}] sample {i}: {values}")
    except KeyboardInterrupt:
        print("\nStopped by user.")
        await client.stop_streaming()

    # 4. Disconnect
    await client.disconnect()
    print("Disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stream QSense 9DOF IMU data over BLE.")
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Streaming duration in seconds (default: 10)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help="Sensor sampling rate in Hz (e.g. 200). Enables per-sample timestamps.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.duration, args.rate))
