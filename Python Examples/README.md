# Python Examples — QSense 9DOF IMU BLE Streaming

Stream real-time 9DOF IMU data from a **QSense motion sensor** over **Bluetooth Low Energy** using Python.  
No QSense USB dongle required — connects directly from a **Raspberry Pi** (or any Linux host with Bluetooth 4.0+).

## Requirements

| Component | Detail |
|-----------|--------|
| **Hardware** | Raspberry Pi CM4 (or any board with BLE support) + QSense sensor |
| **OS** | Raspberry Pi OS / Linux |
| **Python** | 3.9+ |

## Sensor Specifications

| Parameter | Value |
|-----------|-------|
| IMU | 9-DOF (accelerometer, gyroscope, magnetometer) |
| Sampling rate | 1 – 800 Hz (application dependent) |
| Multi-sensor rates | 1–2 sensors: 400 Hz, 3–6: 200 Hz, 7–12: 100 Hz |
| Synchronization | < 60 µs (TimeSync mode) |
| Latency | 7.5 – 15 ms (mode dependent) |
| Orientation accuracy | Static < 1°, drift < 0.5° |
| Wireless | BLE 5.2, 2 Mbps, Data Length Extension |
| Battery | 140 mAh Li-Po (12 – 20 h depending on mode) |
| Size / Weight | 38.9 × 24.3 × 10.2 mm, 8 g, IP67 |

See [`SPEC.md`](SPEC.md) §6 for detailed timing and synchronization documentation.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the streaming example
python stream_example.py

# Stream for a custom duration
python stream_example.py --duration 30

# Stream at 200 Hz with per-sample timestamps
python stream_example.py --rate 200 --duration 10
```

## Files

| File | Description |
|------|-------------|
| `SPEC.md` | Full specification of the BLE streaming protocol and module design |
| `qsense_parser.py` | Pure-Python Core Interface packet builder & parser (no BLE dependency) |
| `qsense_ble.py` | Async BLE client using [bleak](https://github.com/hbldh/bleak) — scan, connect, stream |
| `stream_example.py` | Runnable CLI example that discovers a sensor and prints live IMU data |
| `requirements.txt` | Python dependencies |
| `tests/` | Unit tests (`pytest`) for both modules |

## Running Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

## Usage in Your Own Code

```python
import asyncio
from qsense_ble import QSenseBleClient

async def main():
    # Pass sampling_rate for per-sample timestamps (essential at high rates)
    client = QSenseBleClient(sampling_rate=200)
    await client.scan()
    await client.connect()

    async for frame in client.stream(duration=10):
        for sample in frame["samples"]:
            print(sample["timestamp"], sample)

    await client.disconnect()

asyncio.run(main())
```

## High-Rate Streaming (up to 800 Hz)

The sensor supports sampling rates from **1 to 800 Hz**.  At high rates the
sensor **buffers** multiple samples per BLE packet (e.g. 12 raw samples at
200 Hz).  Pass `sampling_rate` to get **per-sample timestamps** interpolated
from the packet header:

```python
client = QSenseBleClient(sampling_rate=200)
```

The `sampling_rate` parameter is validated against the hardware maximum
(800 Hz).

### Multi-Sensor Rate Limits (via BLE Dongle)

| Sensors | Max Rate |
|---------|----------|
| 1 – 2 | 400 Hz |
| 3 – 6 | 200 Hz |
| 7 – 12 | 100 Hz |

### Operating Modes

- **TimeSync Mode** — continuous wireless synchronization (< 60 µs accuracy),
  absolute timestamps, 15 ms minimum latency
- **Low Latency Mode** — minimum 7.5 ms latency, local timestamps,
  ≤ 2 ms/min drift

Without `sampling_rate`, all samples in a packet share the same header
timestamp.  See [`SPEC.md`](SPEC.md) §6 for full details on buffering,
timestamp interpolation, and BLE connection interval tuning.

## Protocol Summary

The QSense sensor uses a **Nordic UART Service** over BLE:

- **Service UUID**: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- **RX** (write to sensor): `6e400002-b5a3-f393-e0a9-e50e24dcca9e`
- **TX** (receive from sensor): `6e400003-b5a3-f393-e0a9-e50e24dcca9e`

See [`SPEC.md`](SPEC.md) for the full protocol specification including packet formats,
memory map, data modes, and scale factors.
