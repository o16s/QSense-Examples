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
| **Sensor** | QSense 9DOF IMU Motion Sensor (38.9 × 24.3 × 10.2 mm, 8 g, IP67) |
| **Host** | Raspberry Pi CM4 (or any Linux board with Bluetooth 4.0+) |
| **OS** | Raspberry Pi OS (Bookworm / Bullseye) or equivalent Linux |
| **Python** | 3.9 or later |
| **BLE library** | [bleak](https://github.com/hbldh/bleak) ≥ 0.21 |

### 1.1  Sensor Hardware Summary

| Parameter | Value |
|-----------|-------|
| IMU | 9-DOF (Accelerometer + Gyroscope + Magnetometer) |
| Sampling rate | 1 – 800 Hz (application dependent) |
| Wireless | BLE 5.2, up to 2 Mbps, Data Length Extension (DLE) |
| Battery | 140 mAh Li-Po (≥ 12 h TimeSync, up to 20 h Low Latency) |
| Orientation accuracy | Static error < 1°, drift < 0.5° (quaternion mode) |
| Dimensions | 38.9 × 24.3 × 10.2 mm |
| Weight | 8 g |
| Enclosure | IP67 |
| Interface | Micro-USB (charging & wired comms), NUS over BLE |

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
| `0x0000001D` | 1 | Connection Interval |
| `0x0000001E` | 1 | Sync Status |
| `0x00000024` | 4 | Time (Unix timestamp, seconds) |
| `0x0000003C` | 1 | Data Mode |
| `0x0000003D` | 2 | Timesync (controls TimeSync / Low Latency mode) |
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

Datasheet values are given in milli-units.  The parser stores pre-converted
values so that `raw_int16 × scale` yields the final physical value directly.

**Accelerometer** (by range index):

| Index | Range | Datasheet | Scale (g/LSB) |
|-------|-------|-----------|---------------|
| 0 | ±2 g | 0.061 mg/LSB | 0.000061 |
| 1 | ±16 g | 0.488 mg/LSB | 0.000488 |
| 2 | ±4 g | 0.122 mg/LSB | 0.000122 |
| 3 | ±8 g | 0.244 mg/LSB | 0.000244 |

**Gyroscope** (by range index — indices 3 and 5 are unused by hardware):

| Index | Range | Datasheet | Scale (dps/LSB) |
|-------|-------|-----------|-----------------|
| 0 | ±250 dps | 8.75 mdps/LSB | 0.00875 |
| 1 | ±125 dps | 4.375 mdps/LSB | 0.004375 |
| 2 | ±500 dps | 17.5 mdps/LSB | 0.0175 |
| 4 | ±1000 dps | 35 mdps/LSB | 0.035 |
| 6 | ±2000 dps | 70 mdps/LSB | 0.07 |

**Magnetometer**: ±50 Gauss, fixed scale of **0.0015 Gauss/LSB**
(datasheet: 1.5 mGauss/LSB).

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

## 6  Timing, Synchronization & High-Rate Streaming

### 6.1  Operating Modes

The QSense sensor supports two operating modes with different timing
characteristics:

#### TimeSync Mode (High-Precision Synchronization)

Designed for applications requiring deterministic timing and frame-accurate
multi-sensor alignment.

| Parameter | Value |
|-----------|-------|
| Latency (minimum) | 15 ms |
| Latency (typical) | 7.5 ms × number of sensors |
| Synchronization accuracy (typical) | < 60 µs |
| Synchronization accuracy (maximum) | < 150 µs |
| Battery life | ≥ 12 hours |

All sensors are continuously synchronized wirelessly during measurement.
Every sample is tagged with an absolute date/time stamp.  Enables reliable
multi-sensor fusion and alignment with external systems.

#### Low Latency Mode (Minimal Delay Streaming)

Designed for closed-loop applications where responsiveness is more important
than long-term timing precision.

| Parameter | Value |
|-----------|-------|
| Latency (minimum) | 7.5 ms |
| Latency (typical) | 7.5 ms × number of sensors |
| Time drift | ≤ 2 ms per minute (worst case) |
| BLE offset | Up to 7.5 ms per device (connection interval) |
| Battery life | Up to 20 hours |

Each sensor timestamps data locally using its internal clock — no active
runtime synchronization.  Drift may accumulate over time.

#### Selecting the Mode

Before measurement, device clocks can be synchronized to an external host
(PC / tablet).  The `Timesync` register at address `0x0000003D` controls
the operating mode.  In custom implementations, time can also be set
programmatically via the device interface (write to the `Time` register at
`0x00000024`).

### 6.2  Multi-Sensor Sampling Rate Limits

Maximum achievable sample rate depends on the number of active sensors
(via QSense BLE Dongle):

| Sensors | Maximum Rate |
|---------|-------------|
| 1 – 2 | 400 Hz |
| 3 – 6 | 200 Hz |
| 7 – 12 | 100 Hz |

The sensor hardware supports sampling rates from **1 Hz to 800 Hz**
(application dependent).  Rates above the per-sensor-count limits are
constrained by BLE dongle bandwidth.

When connecting directly from a Raspberry Pi (without the dongle), a single
sensor can achieve rates up to 400 Hz depending on the BLE connection
parameters.

### 6.3  Buffering

At high sampling rates the sensor **buffers** multiple samples into each BLE
notification to reduce radio overhead.  The **buffering factor** is encoded in
the upper nibble of stream payload byte 0 (see §4.1).

For example, in **Raw mode** (18 bytes/sample), the 237-byte payload has
227 usable bytes after the 10-byte header, giving a maximum of
**⌊227 / 18⌋ = 12 samples per packet**.  At 200 Hz with buffering = 12 the
sensor sends ≈ 16.7 packets/s — well within BLE throughput limits.

### 6.4  Per-Sample Timestamps

Each stream packet carries **one** header timestamp (§4.1).  When the
buffering factor > 1 every sample within the packet was captured at a
different physical time.

When `sampling_rate` is provided to `parse_stream_payload()` or to
`QSenseBleClient`, the library **interpolates** a per-sample timestamp:

```
sample[i].timestamp = header.timestamp + i × (1 / sampling_rate)
```

The header timestamp is treated as the time of the **first** sample;
subsequent samples are spaced at `1 / sampling_rate` intervals.

Without a `sampling_rate` the sample dicts contain no `"timestamp"` key
and only the header-level timestamp is available.

### 6.5  BLE Connection Interval

BLE throughput depends on the **connection interval** negotiated between host
and sensor.  On a Raspberry Pi (BlueZ), the default may be too slow for high
rates.  If you observe data loss:

1. Request a shorter connection interval via BlueZ (7.5 – 15 ms is ideal).
2. Ensure no other BLE-intensive peripherals compete for airtime.
3. Keep the Raspberry Pi physically close to the sensor (< 2 m for best
   results).

### 6.6  Orientation Accuracy (Quaternion Mode)

| Parameter | Value |
|-----------|-------|
| Maximum static error | < 1° |
| Maximum drift | < 0.5° |

Accuracy is influenced by magnetic disturbance and gyroscope bias.  Internal
compensation strategies are implemented to minimize these effects.

---

## 7  Module Design

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

## 8  Testing Strategy (TDD)

1. **Red** — write tests against the public API of `qsense_parser` and
   `qsense_ble` before any implementation exists.
2. **Green** — implement the minimum code to make each test pass.
3. **Refactor** — clean up while keeping tests green.

Tests use `pytest` and, for BLE, `unittest.mock` / `pytest-asyncio`
to simulate `bleak` without real hardware.

---

## 9  Example Usage

```python
import asyncio
from qsense_ble import QSenseBleClient

async def main():
    # Pass sampling_rate for per-sample timestamps at high rates
    client = QSenseBleClient(sampling_rate=200)
    await client.scan()
    await client.connect()

    async for frame in client.stream(duration=10):
        for sample in frame["samples"]:
            print(sample["timestamp"], sample)

    await client.disconnect()

asyncio.run(main())
```

---

## 10  References

- `Sensor Interfaces/QSense-Sensor-Interface-v3.pdf` — full protocol specification
- `Sensor Interfaces/CoreInterfaceParser.py` — reference Python parser
- `C# APIs/QSenseDotNet examples/BleService.cs` — reference BLE integration
