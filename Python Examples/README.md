# Python Examples — QSense 9DOF IMU BLE Streaming

Stream real-time 9DOF IMU data from a **QSense motion sensor** over **Bluetooth Low Energy** using Python.  
No QSense USB dongle required — connects directly from a **Raspberry Pi** (or any Linux host with Bluetooth 4.0+).

## Requirements

| Component | Detail |
|-----------|--------|
| **Hardware** | Raspberry Pi CM4 (or any board with BLE support) + QSense sensor |
| **OS** | Raspberry Pi OS / Linux |
| **Python** | 3.9+ |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the streaming example
python stream_example.py

# Stream for a custom duration
python stream_example.py --duration 30
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
    client = QSenseBleClient()
    await client.scan()
    await client.connect()

    async for frame in client.stream(duration=10):
        header = frame["header"]
        for sample in frame["samples"]:
            print(sample)

    await client.disconnect()

asyncio.run(main())
```

## Protocol Summary

The QSense sensor uses a **Nordic UART Service** over BLE:

- **Service UUID**: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- **RX** (write to sensor): `6e400002-b5a3-f393-e0a9-e50e24dcca9e`
- **TX** (receive from sensor): `6e400003-b5a3-f393-e0a9-e50e24dcca9e`

See [`SPEC.md`](SPEC.md) for the full protocol specification including packet formats,
memory map, data modes, and scale factors.
