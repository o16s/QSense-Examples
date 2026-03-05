#!/usr/bin/env python3
"""
multi_stream_example.py — Stream from two QSense sensors simultaneously over BLE.

Run on a Raspberry Pi (CM4 or similar with Bluetooth):

    python multi_stream_example.py                      # 10 s at default rate
    python multi_stream_example.py --duration 30        # 30 s
    python multi_stream_example.py --rate 200           # 200 Hz with per-sample timestamps

Each QSenseBleClient instance manages its own BLE connection, so streaming
from multiple sensors only requires one client per device.  Async tasks let
both streams run concurrently without threads.
"""

import argparse
import asyncio

from qsense_ble import QSenseBleClient


async def stream_sensor(
    label: str,
    client: QSenseBleClient,
    duration: float,
) -> None:
    """Print IMU frames from *client* for *duration* seconds."""
    async for frame in client.stream(duration=duration):
        header = frame["header"]
        for i, sample in enumerate(frame["samples"]):
            ts = sample.get("timestamp", header.timestamp)
            values = "  ".join(
                f"{k}={v:+.4f}"
                for k, v in sample.items()
                if k != "timestamp"
            )
            print(f"[{label}] [{ts:%H:%M:%S.%f}] sample {i}: {values}")


async def main(duration: float, sampling_rate: float | None) -> None:
    # 1. Scan — a single scan discovers all nearby QSense devices.
    scout = QSenseBleClient()
    print("Scanning for QSense sensors …")
    devices = await scout.scan(timeout=5.0)

    if len(devices) < 2:
        print(
            f"Found {len(devices)} QSense sensor(s) — need at least 2. "
            "Make sure both sensors are powered on and nearby."
        )
        return

    print(f"Found {len(devices)} sensors:")
    for d in devices:
        print(f"  • {d.name} ({d.address})")

    # 2. Create one client per sensor and connect.
    clients: list[tuple[str, QSenseBleClient]] = []
    for idx, dev in enumerate(devices[:2]):
        label = f"Sensor {idx + 1}"
        client = QSenseBleClient(sampling_rate=sampling_rate)
        print(f"Connecting to {label}: {dev.name} ({dev.address}) …")
        await client.connect(device=dev)
        clients.append((label, client))
        print(f"  {label} connected.")

    # 3. Stream both sensors concurrently.
    rate_info = f" at {sampling_rate} Hz" if sampling_rate else ""
    print(f"\nStreaming for {duration} seconds{rate_info} (Ctrl+C to stop early) …\n")
    try:
        await asyncio.gather(*(
            stream_sensor(label, client, duration)
            for label, client in clients
        ))
    except KeyboardInterrupt:
        print("\nStopped by user.")
        for _, client in clients:
            await client.stop_streaming()

    # 4. Disconnect all.
    for label, client in clients:
        await client.disconnect()
        print(f"{label} disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stream QSense 9DOF IMU data from two sensors over BLE.",
    )
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
        dest="sampling_rate",
        help="Sensor sampling rate in Hz (e.g. 200). Enables per-sample timestamps.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.duration, args.sampling_rate))
