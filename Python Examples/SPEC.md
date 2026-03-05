# QSense 9DOF IMU Sensor — Python BLE Streaming Specification

## Overview

This specification describes how to **stream real-time 9DOF IMU data** from a
QSense motion sensor over **Bluetooth Low Energy (BLE)** using Python.
The target platform is a **Raspberry Pi** (e.g. CM4 with on-board Bluetooth) —
no QSense USB dongle is required.

---

## 1  Hardware & Software Requirements

| Component | Detail |
|-----------|--------|
| **Sensor** | QSense 9DOF IMU Motion Sensor |
| **Host** | Raspberry Pi CM4 (or any Linux board with Bluetooth 4.0+) |
| **OS** | Raspberry Pi OS (Bookworm / Bullseye) or equivalent Linux |
| **Python** | 3.9 or later |
| **BLE library** | [bleak](https://github.com/hbldh/bleak) ≥ 0.21 |

---

## 2  BLE Transport

The QSense sensor exposes a **Nordic UART Service (NUS)**.

| Role | UUID |
|------|------|
| **Service** | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| **RX Characteristic** (host → sensor, write) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| **TX Characteristic** (sensor → host, notify) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |

The sensor advertises with the local name **`qsense`** (case-insensitive).

---

## 3  Protocol — Core Interface

All communication uses the **Core Interface** binary packet format.

### 3.1  Packet Structure

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 byte | Opcode |
| 1 | 4 bytes | Address (little-endian uint32) |
| 5 | 2 bytes | Length (little-endian uint16) |
| 7 | *Length* bytes | Data payload |

### 3.2  Opcodes

| Value | Name | Direction |
|-------|------|-----------|
| 1 | **Read** | Host → Sensor — request memory at *Address* |
| 2 | **Data** | Sensor → Host — response carrying requested data |
| 3 | **Abort** | Host → Sensor — stop streaming |
| 4 | **Stream** | Host → Sensor — start streaming |

### 3.3  Memory Map (selected registers)

| Address | Size | Register |
|---------|------|----------|
| `0x00000000` | 4 | WhoAmI (`0x324D5351`) |
| `0x00000004` | 8 | Sensor Id |
| `0x0000000C` | 8 | MAC Address |
| `0x00000014` | 4 | Firmware Version (patch · minor · major) |
| `0x00000018` | 1 | Battery (%) |
| `0x0000003C` | 1 | Data Mode |
| `0x0000003F` | 1 | Algorithm Selection |

Control memory spans `0x00000000 – 0x0000003F` (64 bytes).

---

## 4  Stream Packets

Streaming is started by writing a **Stream** command to the RX characteristic:

```
Opcode = 0x04
Address = 0x00000100  (stream memory)
Length  = 237          (0x00ED)
```

The sensor then begins sending **Data** packets (opcode `0x02`) on the
TX characteristic with address `0x00000100` and 237 bytes of payload.

### 4.1  Stream Header (bytes 0 – 9 of payload)

| Offset | Bits | Field |
|--------|------|-------|
| 0 | [3:0] | Data Mode (0 = Mixed, 1 = Raw, 2 = Quat, 3 = Optimized, 4 = Quat+Mag) |
| 0 | [7:4] | Buffering factor |
| 1–4 | 32 | Unix timestamp — seconds (LE uint32) |
| 5–6 | 16 | Sub-second counter × 1.25 ms (LE uint16) |
| 7 | [2:0] | Magnetic interference level |
| 7 | [7:3] | Battery (value × 6.25 %) |
| 8 | 8 | Annotation |
| 9 | [0] | Sync status |
| 9 | [3:1] | Gyroscope range index |
| 9 | [5:4] | Accelerometer range index |

### 4.2  Scale Factors

**Accelerometer** (by range index):

| Index | Range | Scale (g/LSB) |
|-------|-------|---------------|
| 0 | ±2 g | 0.000061 |
| 1 | ±16 g | 0.000488 |
| 2 | ±4 g | 0.000122 |
| 3 | ±8 g | 0.000244 |

**Gyroscope** (by range index):

| Index | Range | Scale (dps/LSB) |
|-------|-------|-----------------|
| 0 | 250 dps | 0.00875 |
| 1 | 125 dps | 0.004375 |
| 2 | 500 dps | 0.0175 |
| 4 | 1000 dps | 0.035 |
| 6 | 2000 dps | 0.07 |

**Magnetometer**: fixed scale of **0.0015** gauss/LSB.

### 4.3  Data Modes & Payload Layout (after header)

All multi-byte sensor values are **signed 16-bit little-endian** integers.

**Raw** (mode 1): `buffering` samples × 18 bytes each
(AccX, AccY, AccZ, GyrX, GyrY, GyrZ, MagX, MagY, MagZ — 9 × int16)

**Quaternion** (mode 2): `buffering` samples × 8 bytes each
(q0, q1, q2, q3 — 4 × int16, divide by 32768 to normalise)

**Optimized** (mode 3): Quaternion (8 bytes) + Acc+Gyr (12 bytes, no mag)

**Mixed** (mode 0): Raw sample (18 bytes) + Quaternion (8 bytes) + Acc+Gyr (12 bytes)

**Quat+Mag** (mode 4): Quaternion (8 bytes) + Magnetometer (6 bytes)

---

## 5  Connection Flow

```
1. Scan for BLE peripherals advertising the name "qsense"
2. Connect to the discovered device
3. Discover the NUS service (6e400001-…)
4. Subscribe to notifications on the TX characteristic (6e400003-…)
5. Write a Read command to RX (6e400002-…) to read control memory and verify WhoAmI
6. Write the Stream command to RX to begin streaming
7. Receive and parse Data packets from TX notifications
8. Write an Abort command to RX to stop streaming
9. Disconnect
```

---

## 6  Module Design

The Python Examples folder contains:

| File | Purpose |
|------|---------|
| `qsense_parser.py` | Reusable, pure-Python module that creates & parses Core Interface packets. Fully testable without hardware. |
| `qsense_ble.py` | Async BLE layer using `bleak`. Scans, connects, subscribes, and exposes an async stream of parsed IMU frames. |
| `stream_example.py` | Runnable CLI example — discovers a QSense sensor, streams data for a configurable duration, and prints values. |
| `requirements.txt` | Python dependencies (`bleak>=0.21`). |
| `tests/test_qsense_parser.py` | Unit tests for `qsense_parser.py` (protocol encoding/decoding). |
| `tests/test_qsense_ble.py` | Unit tests for `qsense_ble.py` (mocked BLE interactions). |
| `README.md` | Quick-start guide for running on Raspberry Pi. |

---

## 7  Testing Strategy (TDD)

1. **Red** — write tests against the public API of `qsense_parser` and
   `qsense_ble` before any implementation exists.
2. **Green** — implement the minimum code to make each test pass.
3. **Refactor** — clean up while keeping tests green.

Tests use `pytest` and, for BLE, `unittest.mock` / `pytest-asyncio`
to simulate `bleak` without real hardware.

---

## 8  Example Usage

```python
import asyncio
from qsense_ble import QSenseBleClient

async def main():
    client = QSenseBleClient()
    await client.scan()
    await client.connect()

    async for frame in client.stream(duration=10):
        print(frame)

    await client.disconnect()

asyncio.run(main())
```

---

## 9  References

- `Sensor Interfaces/QSense-Sensor-Interface-v3.pdf` — full protocol specification
- `Sensor Interfaces/CoreInterfaceParser.py` — reference Python parser
- `C# APIs/QSenseDotNet examples/BleService.cs` — reference BLE integration
