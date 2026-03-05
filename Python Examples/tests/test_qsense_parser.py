import struct
import pytest
import sys
import os

# Allow imports from parent directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qsense_parser import (
    CoreInterfaceParser,
    Raw9Dof,
    StreamHeader,
    parse_stream_payload,
)


# ---------------------------------------------------------------------------
# Packet creation
# ---------------------------------------------------------------------------

class TestCreateReadPacket:
    def test_opcode_is_read(self):
        pkt = CoreInterfaceParser.create_read_packet(0x00000000, 64)
        assert pkt[0] == CoreInterfaceParser.Opcode.Read

    def test_address_encoded_little_endian(self):
        pkt = CoreInterfaceParser.create_read_packet(0x00000014, 4)
        assert struct.unpack_from("<I", pkt, 1)[0] == 0x00000014

    def test_length_encoded_little_endian(self):
        pkt = CoreInterfaceParser.create_read_packet(0x00000000, 64)
        assert struct.unpack_from("<H", pkt, 5)[0] == 64

    def test_packet_is_7_bytes(self):
        pkt = CoreInterfaceParser.create_read_packet(0, 1)
        assert len(pkt) == 7


class TestCreateAbortPacket:
    def test_opcode_is_abort(self):
        pkt = CoreInterfaceParser.create_abort_packet()
        assert pkt[0] == CoreInterfaceParser.Opcode.Abort

    def test_length_is_1(self):
        pkt = CoreInterfaceParser.create_abort_packet()
        assert len(pkt) == 1


class TestCreateStreamPacket:
    def test_opcode_is_stream(self):
        pkt = CoreInterfaceParser.create_stream_packet()
        assert pkt[0] == CoreInterfaceParser.Opcode.Stream

    def test_address_is_stream_memory(self):
        pkt = CoreInterfaceParser.create_stream_packet()
        assert struct.unpack_from("<I", pkt, 1)[0] == CoreInterfaceParser.STREAM_MEMORY_ADDRESS

    def test_length_is_stream_size(self):
        pkt = CoreInterfaceParser.create_stream_packet()
        assert struct.unpack_from("<H", pkt, 5)[0] == CoreInterfaceParser.STREAM_MEMORY_SIZE


class TestCreateWritePacket:
    def test_opcode_is_data(self):
        pkt = CoreInterfaceParser.create_write_packet(0x0000003C, bytes([0x01]))
        assert pkt[0] == CoreInterfaceParser.Opcode.Data

    def test_data_appended(self):
        pkt = CoreInterfaceParser.create_write_packet(0x0000003C, bytes([0x01]))
        assert pkt[7] == 0x01

    def test_length_matches_data(self):
        data = bytes([0x01, 0x02, 0x03])
        pkt = CoreInterfaceParser.create_write_packet(0, data)
        assert struct.unpack_from("<H", pkt, 5)[0] == 3
        assert len(pkt) == 7 + 3


# ---------------------------------------------------------------------------
# Packet parsing — control memory
# ---------------------------------------------------------------------------

class TestParseControlMemory:
    def _make_data_packet(self, address: int, payload: bytes) -> bytes:
        """Build a minimal Data response packet."""
        pkt = bytearray(7 + len(payload))
        pkt[0] = CoreInterfaceParser.Opcode.Data
        struct.pack_into("<I", pkt, 1, address)
        struct.pack_into("<H", pkt, 5, len(payload))
        pkt[7:] = payload
        return bytes(pkt)

    def test_parse_whoami(self):
        payload = struct.pack("<I", CoreInterfaceParser.WHOAMI_VALUE)
        pkt = self._make_data_packet(0x00000000, payload)
        result = CoreInterfaceParser.parse_packet(pkt)
        assert result is not None
        assert result.get("WhoAmI") == CoreInterfaceParser.WHOAMI_VALUE

    def test_parse_battery(self):
        # Battery is at offset 0x18, 1 byte
        payload = bytearray(0x19)  # enough bytes to cover offset 0x18
        payload[0x18] = 85  # 85%
        pkt = self._make_data_packet(0x00000000, bytes(payload))
        result = CoreInterfaceParser.parse_packet(pkt)
        assert result.get("Battery") == 85

    def test_parse_version(self):
        # Version at offset 0x14, 4 bytes: [patch, minor, major, 0]
        payload = bytearray(0x18)
        payload[0x14] = 3   # patch
        payload[0x15] = 2   # minor
        payload[0x16] = 1   # major
        payload[0x17] = 0
        pkt = self._make_data_packet(0x00000000, bytes(payload))
        result = CoreInterfaceParser.parse_packet(pkt)
        assert result.get("Version") == "v1.2.3"


# ---------------------------------------------------------------------------
# Stream header parsing
# ---------------------------------------------------------------------------

class TestParseStreamHeader:
    def _make_stream_header(
        self,
        mode: int = 1,
        buffering: int = 1,
        seconds: int = 1000,
        sub_seconds: int = 0,
        flags: int = 0,
        annotation: int = 0,
        config: int = 0,
    ) -> bytes:
        header = bytearray(10)
        header[0] = (buffering << 4) | (mode & 0x0F)
        struct.pack_into("<I", header, 1, seconds)
        struct.pack_into("<H", header, 5, sub_seconds)
        header[7] = flags
        header[8] = annotation
        header[9] = config
        return bytes(header)

    def test_data_mode(self):
        hdr = self._make_stream_header(mode=1)
        parsed = StreamHeader.from_bytes(hdr)
        assert parsed.data_mode == 1

    def test_buffering(self):
        hdr = self._make_stream_header(buffering=5)
        parsed = StreamHeader.from_bytes(hdr)
        assert parsed.buffering == 5

    def test_battery_from_flags(self):
        # battery bits are [7:3] of byte 7, value * 6.25
        hdr = self._make_stream_header(flags=(8 << 3))
        parsed = StreamHeader.from_bytes(hdr)
        assert parsed.battery == pytest.approx(8 * 6.25)

    def test_acc_range_index(self):
        # bits [5:4] of byte 9
        config = 0x02 << 4  # acc range index = 2
        hdr = self._make_stream_header(config=config)
        parsed = StreamHeader.from_bytes(hdr)
        assert parsed.acc_range_index == 2

    def test_gyr_range_index(self):
        # bits [3:1] of byte 9
        config = 0x02 << 1  # gyr range index = 2
        hdr = self._make_stream_header(config=config)
        parsed = StreamHeader.from_bytes(hdr)
        assert parsed.gyr_range_index == 2


# ---------------------------------------------------------------------------
# Raw9Dof parsing
# ---------------------------------------------------------------------------

class TestRaw9Dof:
    def test_acc_gyr_mag_with_scale(self):
        buf = bytearray(18)
        # AccX = 1000 raw
        struct.pack_into("<h", buf, 0, 1000)
        # GyrX = 2000 raw
        struct.pack_into("<h", buf, 6, 2000)
        # MagX = 500 raw
        struct.pack_into("<h", buf, 12, 500)

        sample = Raw9Dof(buf, 0, acc_scale=0.000061, gyr_scale=0.00875, include_mag=True)
        assert sample.AccX == pytest.approx(1000 * 0.000061)
        assert sample.GyrX == pytest.approx(2000 * 0.00875)
        assert sample.MagX == pytest.approx(500 * 0.0015)

    def test_no_mag(self):
        buf = bytearray(12)
        struct.pack_into("<h", buf, 0, 100)
        sample = Raw9Dof(buf, 0, acc_scale=0.000061, gyr_scale=0.00875, include_mag=False)
        assert sample.AccX == pytest.approx(100 * 0.000061)
        assert not hasattr(sample, "MagX")


# ---------------------------------------------------------------------------
# Stream payload parsing
# ---------------------------------------------------------------------------

class TestParseStreamPayload:
    @staticmethod
    def _make_raw_stream_data(mode=1, buffering=1, acc_idx=0, gyr_idx=0) -> bytes:
        """Build a synthetic 237-byte stream payload (raw mode, 1 sample)."""
        data = bytearray(237)
        data[0] = (buffering << 4) | (mode & 0x0F)
        # config byte: acc_range bits [5:4], gyr_range bits [3:1]
        data[9] = (acc_idx << 4) | (gyr_idx << 1)
        # Write one raw sample (9 × int16) starting at offset 10
        for i in range(9):
            struct.pack_into("<h", data, 10 + i * 2, (i + 1) * 100)
        return bytes(data)

    def test_raw_mode_returns_samples(self):
        data = self._make_raw_stream_data(mode=1, buffering=1)
        result = parse_stream_payload(data)
        assert result is not None
        assert "header" in result
        assert "samples" in result
        assert len(result["samples"]) == 1

    def test_raw_sample_has_acc_gyr_mag(self):
        data = self._make_raw_stream_data(mode=1, buffering=1)
        result = parse_stream_payload(data)
        s = result["samples"][0]
        assert "AccX" in s and "AccY" in s and "AccZ" in s
        assert "GyrX" in s and "GyrY" in s and "GyrZ" in s
        assert "MagX" in s and "MagY" in s and "MagZ" in s

    def test_quat_mode_returns_quaternions(self):
        data = bytearray(237)
        data[0] = (1 << 4) | 2  # buffering=1, mode=Quat
        for i in range(4):
            struct.pack_into("<h", data, 10 + i * 2, (i + 1) * 1000)
        result = parse_stream_payload(bytes(data))
        assert len(result["samples"]) == 1
        s = result["samples"][0]
        assert "q0" in s and "q1" in s and "q2" in s and "q3" in s
