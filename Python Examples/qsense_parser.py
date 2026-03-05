"""
qsense_parser — Pure-Python packet builder & parser for the QSense Core Interface.

This module contains no BLE or I/O dependencies, so it can be fully unit-tested
without hardware.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Raw 9-DOF sample
# ---------------------------------------------------------------------------

class Raw9Dof:
    """Parse a single raw 9-DOF sample from a byte buffer."""

    MAG_SCALE = 0.0015

    def __init__(
        self,
        buffer: bytes,
        position: int,
        acc_scale: float | None = None,
        gyr_scale: float | None = None,
        include_mag: bool = False,
    ):
        if acc_scale is not None and gyr_scale is not None:
            self.AccX = struct.unpack_from("<h", buffer, position + 0)[0] * acc_scale
            self.AccY = struct.unpack_from("<h", buffer, position + 2)[0] * acc_scale
            self.AccZ = struct.unpack_from("<h", buffer, position + 4)[0] * acc_scale
            self.GyrX = struct.unpack_from("<h", buffer, position + 6)[0] * gyr_scale
            self.GyrY = struct.unpack_from("<h", buffer, position + 8)[0] * gyr_scale
            self.GyrZ = struct.unpack_from("<h", buffer, position + 10)[0] * gyr_scale
            if include_mag:
                self.MagX = struct.unpack_from("<h", buffer, position + 12)[0] * self.MAG_SCALE
                self.MagY = struct.unpack_from("<h", buffer, position + 14)[0] * self.MAG_SCALE
                self.MagZ = struct.unpack_from("<h", buffer, position + 16)[0] * self.MAG_SCALE
        else:
            self.MagX = struct.unpack_from("<h", buffer, position + 0)[0] * self.MAG_SCALE
            self.MagY = struct.unpack_from("<h", buffer, position + 2)[0] * self.MAG_SCALE
            self.MagZ = struct.unpack_from("<h", buffer, position + 4)[0] * self.MAG_SCALE


# ---------------------------------------------------------------------------
# Stream header
# ---------------------------------------------------------------------------

# Accelerometer scale factors in g/LSB (datasheet: 0.061 – 0.488 mg/LSB)
ACC_SCALE_FACTORS = [0.000061, 0.000488, 0.000122, 0.000244]
# Gyroscope scale factors in dps/LSB (datasheet: 4.375 – 70 mdps/LSB)
# Indices 3 and 5 are unused by hardware — kept as 0.0 placeholders.
GYR_SCALE_FACTORS = [0.008750, 0.004375, 0.0175, 0.0, 0.035, 0.0, 0.07]
ACC_RANGES = ["2g", "16g", "4g", "8g"]
# Sparse array: indices 3 and 5 are unused by hardware.
GYR_RANGES = ["250dps", "125dps", "500dps", "", "1000dps", "", "2000dps"]
DATA_MODES = ["Mixed", "Raw", "Quaternion", "Optimized", "Quat+Mag"]
INTERFERENCE_LEVELS = [
    "",
    "None",
    "Soft-iron interference",
    "Hard-iron interference",
    "Change of environment detected",
]


@dataclass
class StreamHeader:
    data_mode: int = 0
    buffering: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    interference: str = ""
    battery: float = 0.0
    annotation: int = 0
    sync_status: bool = False
    acc_range_index: int = 0
    gyr_range_index: int = 0

    @property
    def acc_scale(self) -> float:
        return ACC_SCALE_FACTORS[self.acc_range_index]

    @property
    def gyr_scale(self) -> float:
        return GYR_SCALE_FACTORS[self.gyr_range_index]

    @property
    def acc_range(self) -> str:
        return ACC_RANGES[self.acc_range_index]

    @property
    def gyr_range(self) -> str:
        return GYR_RANGES[self.gyr_range_index]

    @staticmethod
    def from_bytes(data: bytes) -> "StreamHeader":
        mode = data[0] & 0x0F
        buffering = data[0] >> 4
        seconds = struct.unpack_from("<I", data, 1)[0]
        sub_seconds = struct.unpack_from("<H", data, 5)[0] * 1.25
        timestamp = datetime(1970, 1, 1) + timedelta(seconds=seconds, milliseconds=sub_seconds)
        interference_idx = data[7] & 0x07
        interference = INTERFERENCE_LEVELS[interference_idx] if interference_idx < len(INTERFERENCE_LEVELS) else ""
        battery = (data[7] >> 3) * 6.25
        annotation = data[8]
        sync_status = (data[9] & 0x01) == 1
        gyr_range_index = (data[9] & 0x0E) >> 1
        acc_range_index = (data[9] & 0x30) >> 4
        return StreamHeader(
            data_mode=mode,
            buffering=buffering,
            timestamp=timestamp,
            interference=interference,
            battery=battery,
            annotation=annotation,
            sync_status=sync_status,
            acc_range_index=acc_range_index,
            gyr_range_index=gyr_range_index,
        )


# ---------------------------------------------------------------------------
# Core Interface Parser
# ---------------------------------------------------------------------------

class CoreInterfaceParser:
    class Opcode:
        Read = 1
        Data = 2
        Abort = 3
        Stream = 4

    class PacketFieldAddress:
        Opcode = 0
        Address = 1
        Length = 5
        Data = 7

    class MemoryAddress:
        WhoAmI = 0x00000000
        Id = 0x00000004
        MacAddress = 0x0000000C
        Version = 0x00000014
        Battery = 0x00000018
        MotionLevel = 0x00000019
        OffsetCompensated = 0x0000001A
        MagneticFieldMapped = 0x0000001B
        MagneticFieldProgress = 0x0000001C
        ConnectionInterval = 0x0000001D
        SyncStatus = 0x0000001E
        Ticks100Hz = 0x0000001F
        Pin = 0x00000020
        Time = 0x00000024
        Annotation = 0x00000028
        DeviceState = 0x0000002A
        UiAnimation = 0x0000002C
        DeviceName = 0x00000030
        DataMode = 0x0000003C
        Timesync = 0x0000003D
        AlgorithmSelection = 0x0000003F

    class DataMode:
        Mixed = 0
        Raw = 1
        Quat = 2
        Optimized = 3
        QuatMag = 4

    CONTROL_MEMORY_ADDRESS = 0x00000000
    CONTROL_MEMORY_SIZE = 0x00000040
    STREAM_MEMORY_ADDRESS = 0x00000100
    STREAM_MEMORY_SIZE = 237
    WHOAMI_VALUE = 0x324D5351
    PIN_VALUE = 0x65766F6C

    # Maximum supported sampling rate (Hz) per the QSense datasheet.
    MAX_SAMPLING_RATE = 800

    # Maximum sampling rate per sensor count (via QSense BLE Dongle).
    MAX_RATE_BY_SENSOR_COUNT = {1: 400, 2: 400, 3: 200, 4: 200, 5: 200, 6: 200,
                                7: 100, 8: 100, 9: 100, 10: 100, 11: 100, 12: 100}

    # -- Packet creation ---------------------------------------------------

    @staticmethod
    def create_read_packet(address: int, length: int) -> bytes:
        pkt = bytearray(7)
        pkt[0] = CoreInterfaceParser.Opcode.Read
        struct.pack_into("<I", pkt, 1, address)
        struct.pack_into("<H", pkt, 5, length)
        return bytes(pkt)

    @staticmethod
    def create_write_packet(address: int, data: bytes) -> bytes:
        length = len(data)
        pkt = bytearray(7 + length)
        pkt[0] = CoreInterfaceParser.Opcode.Data
        struct.pack_into("<I", pkt, 1, address)
        struct.pack_into("<H", pkt, 5, length)
        pkt[7 : 7 + length] = data
        return bytes(pkt)

    @staticmethod
    def create_abort_packet() -> bytes:
        return bytes([CoreInterfaceParser.Opcode.Abort])

    @staticmethod
    def create_stream_packet() -> bytes:
        pkt = bytearray(7)
        pkt[0] = CoreInterfaceParser.Opcode.Stream
        struct.pack_into("<I", pkt, 1, CoreInterfaceParser.STREAM_MEMORY_ADDRESS)
        struct.pack_into("<H", pkt, 5, CoreInterfaceParser.STREAM_MEMORY_SIZE)
        return bytes(pkt)

    # -- Packet parsing ----------------------------------------------------

    @staticmethod
    def parse_packet(
        packet: bytes,
        sampling_rate: float | None = None,
    ) -> dict[str, Any] | None:
        """Parse a Core Interface packet and return a dict of fields.

        When *sampling_rate* (Hz) is provided and the packet contains stream
        data, per-sample timestamps are interpolated.
        """
        if len(packet) < 7:
            return None

        opcode = packet[0]
        address = struct.unpack_from("<I", packet, 1)[0]
        length = struct.unpack_from("<H", packet, 5)[0]
        data = packet[7 : 7 + length]

        if address + length <= CoreInterfaceParser.CONTROL_MEMORY_SIZE:
            return CoreInterfaceParser._parse_control_memory(address, length, data)
        elif (
            address == CoreInterfaceParser.STREAM_MEMORY_ADDRESS
            and length == CoreInterfaceParser.STREAM_MEMORY_SIZE
        ):
            return parse_stream_payload(data, sampling_rate=sampling_rate)

        return {"opcode": opcode, "address": address, "length": length}

    @staticmethod
    def _parse_control_memory(address: int, length: int, data: bytes) -> dict[str, Any]:
        result: dict[str, Any] = {}

        def in_range(reg_addr: int, reg_size: int) -> bool:
            return address <= reg_addr and address + length >= reg_addr + reg_size

        def offset(reg_addr: int) -> int:
            return reg_addr - address

        MA = CoreInterfaceParser.MemoryAddress

        if in_range(MA.WhoAmI, 4):
            result["WhoAmI"] = struct.unpack_from("<I", data, offset(MA.WhoAmI))[0]
        if in_range(MA.Id, 8):
            result["Id"] = struct.unpack_from("<Q", data, offset(MA.Id))[0]
        if in_range(MA.MacAddress, 8):
            result["MacAddress"] = struct.unpack_from("<Q", data, offset(MA.MacAddress))[0]
        if in_range(MA.Version, 4):
            o = offset(MA.Version)
            v_major = data[o + 2]
            v_minor = data[o + 1]
            v_patch = data[o]
            result["Version"] = f"v{v_major}.{v_minor}.{v_patch}"
        if in_range(MA.Battery, 1):
            result["Battery"] = data[offset(MA.Battery)]
        if in_range(MA.DataMode, 1):
            result["DataMode"] = data[offset(MA.DataMode)]

        return result


# ---------------------------------------------------------------------------
# Stream payload parsing
# ---------------------------------------------------------------------------

def parse_stream_payload(
    data: bytes,
    sampling_rate: float | None = None,
) -> dict[str, Any]:
    """Parse the 237-byte stream payload into a header + list of samples.

    When *sampling_rate* (Hz) is provided, each sample dict receives a
    ``"timestamp"`` key with the interpolated time for that individual sample.
    The packet header timestamp is treated as the time of the **first** sample;
    subsequent buffered samples are spaced at ``1 / sampling_rate`` intervals.
    """
    header = StreamHeader.from_bytes(data[:10])
    samples: list[dict[str, float]] = []

    if header.data_mode == CoreInterfaceParser.DataMode.Raw:
        samples = _parse_raw_samples(data, header)
    elif header.data_mode == CoreInterfaceParser.DataMode.Quat:
        samples = _parse_quat_samples(data, header)
    elif header.data_mode == CoreInterfaceParser.DataMode.Optimized:
        samples = _parse_optimized_sample(data, header)
    elif header.data_mode == CoreInterfaceParser.DataMode.Mixed:
        samples = _parse_mixed_sample(data, header)
    elif header.data_mode == CoreInterfaceParser.DataMode.QuatMag:
        samples = _parse_quat_mag_sample(data, header)

    if sampling_rate is not None and sampling_rate > 0:
        interval = timedelta(seconds=1.0 / sampling_rate)
        for i, s in enumerate(samples):
            s["timestamp"] = header.timestamp + i * interval

    return {"header": header, "samples": samples}


def _parse_raw_samples(data: bytes, header: StreamHeader) -> list[dict[str, float]]:
    samples = []
    idx = 10
    for _ in range(header.buffering):
        s = Raw9Dof(data, idx, header.acc_scale, header.gyr_scale, include_mag=True)
        samples.append({
            "AccX": s.AccX, "AccY": s.AccY, "AccZ": s.AccZ,
            "GyrX": s.GyrX, "GyrY": s.GyrY, "GyrZ": s.GyrZ,
            "MagX": s.MagX, "MagY": s.MagY, "MagZ": s.MagZ,
        })
        idx += 18
    return samples


def _parse_quat_samples(data: bytes, header: StreamHeader) -> list[dict[str, float]]:
    samples = []
    for i in range(header.buffering):
        idx = 10 + i * 8
        q0 = struct.unpack_from("<h", data, idx)[0] / 32768.0
        q1 = struct.unpack_from("<h", data, idx + 2)[0] / 32768.0
        q2 = struct.unpack_from("<h", data, idx + 4)[0] / 32768.0
        q3 = struct.unpack_from("<h", data, idx + 6)[0] / 32768.0
        samples.append({"q0": q0, "q1": q1, "q2": q2, "q3": q3})
    return samples


def _parse_optimized_sample(data: bytes, header: StreamHeader) -> list[dict[str, float]]:
    q0 = struct.unpack_from("<h", data, 10)[0] / 32768.0
    q1 = struct.unpack_from("<h", data, 12)[0] / 32768.0
    q2 = struct.unpack_from("<h", data, 14)[0] / 32768.0
    q3 = struct.unpack_from("<h", data, 16)[0] / 32768.0
    s = Raw9Dof(data, 18, header.acc_scale, header.gyr_scale, include_mag=False)
    return [{
        "q0": q0, "q1": q1, "q2": q2, "q3": q3,
        "AccX": s.AccX, "AccY": s.AccY, "AccZ": s.AccZ,
        "GyrX": s.GyrX, "GyrY": s.GyrY, "GyrZ": s.GyrZ,
    }]


def _parse_mixed_sample(data: bytes, header: StreamHeader) -> list[dict[str, float]]:
    s0 = Raw9Dof(data, 10, header.acc_scale, header.gyr_scale, include_mag=True)
    q0 = struct.unpack_from("<h", data, 28)[0] / 32768.0
    q1 = struct.unpack_from("<h", data, 30)[0] / 32768.0
    q2 = struct.unpack_from("<h", data, 32)[0] / 32768.0
    q3 = struct.unpack_from("<h", data, 34)[0] / 32768.0
    s1 = Raw9Dof(data, 36, header.acc_scale, header.gyr_scale, include_mag=False)
    return [{
        "AccX0": s0.AccX, "AccY0": s0.AccY, "AccZ0": s0.AccZ,
        "GyrX0": s0.GyrX, "GyrY0": s0.GyrY, "GyrZ0": s0.GyrZ,
        "MagX0": s0.MagX, "MagY0": s0.MagY, "MagZ0": s0.MagZ,
        "q0": q0, "q1": q1, "q2": q2, "q3": q3,
        "AccX1": s1.AccX, "AccY1": s1.AccY, "AccZ1": s1.AccZ,
        "GyrX1": s1.GyrX, "GyrY1": s1.GyrY, "GyrZ1": s1.GyrZ,
    }]


def _parse_quat_mag_sample(data: bytes, header: StreamHeader) -> list[dict[str, float]]:
    q0 = struct.unpack_from("<h", data, 10)[0] / 32768.0
    q1 = struct.unpack_from("<h", data, 12)[0] / 32768.0
    q2 = struct.unpack_from("<h", data, 14)[0] / 32768.0
    q3 = struct.unpack_from("<h", data, 16)[0] / 32768.0
    magX = struct.unpack_from("<h", data, 18)[0] * Raw9Dof.MAG_SCALE
    magY = struct.unpack_from("<h", data, 20)[0] * Raw9Dof.MAG_SCALE
    magZ = struct.unpack_from("<h", data, 22)[0] * Raw9Dof.MAG_SCALE
    return [{
        "q0": q0, "q1": q1, "q2": q2, "q3": q3,
        "MagX": magX, "MagY": magY, "MagZ": magZ,
    }]
