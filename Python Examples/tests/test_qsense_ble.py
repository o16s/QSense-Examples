import struct
import pytest
import asyncio
import sys, os
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Allow imports from parent directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qsense_parser import CoreInterfaceParser
from qsense_ble import QSenseBleClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_device(name="QSense", address="AA:BB:CC:DD:EE:FF"):
    dev = MagicMock()
    dev.name = name
    dev.address = address
    return dev


def _make_stream_notification(mode=1, buffering=1) -> bytes:
    """Build a Core Interface Data packet wrapping a 237-byte stream payload."""
    payload = bytearray(237)
    payload[0] = (buffering << 4) | (mode & 0x0F)
    # acc_range=0, gyr_range=0
    payload[9] = 0x00
    # one raw sample
    for i in range(9):
        struct.pack_into("<h", payload, 10 + i * 2, (i + 1) * 100)
    pkt = bytearray(7 + 237)
    pkt[0] = CoreInterfaceParser.Opcode.Data
    struct.pack_into("<I", pkt, 1, CoreInterfaceParser.STREAM_MEMORY_ADDRESS)
    struct.pack_into("<H", pkt, 5, 237)
    pkt[7:] = payload
    return bytes(pkt)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

class TestScan:
    @pytest.mark.asyncio
    async def test_scan_finds_qsense_device(self):
        fake_dev = _fake_device(name="QSense")
        with patch("qsense_ble.BleakScanner") as MockScanner:
            scanner_instance = AsyncMock()
            scanner_instance.discover = AsyncMock(return_value=[fake_dev])
            MockScanner.return_value = scanner_instance

            client = QSenseBleClient()
            devices = await client.scan(timeout=2.0)
            assert len(devices) == 1
            assert devices[0].name == "QSense"

    @pytest.mark.asyncio
    async def test_scan_ignores_non_qsense(self):
        devs = [_fake_device(name="OtherDevice"), _fake_device(name="qsense-123")]
        with patch("qsense_ble.BleakScanner") as MockScanner:
            scanner_instance = AsyncMock()
            scanner_instance.discover = AsyncMock(return_value=devs)
            MockScanner.return_value = scanner_instance

            client = QSenseBleClient()
            devices = await client.scan(timeout=2.0)
            # Only the qsense device should be returned
            assert len(devices) == 1


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_bleak_client(self):
        fake_dev = _fake_device()
        with patch("qsense_ble.BleakClient") as MockClient:
            mock_conn = AsyncMock()
            mock_conn.is_connected = True
            mock_conn.connect = AsyncMock()
            mock_conn.start_notify = AsyncMock()
            MockClient.return_value = mock_conn

            client = QSenseBleClient()
            client._device = fake_dev
            await client.connect()
            MockClient.assert_called_once_with(fake_dev)
            mock_conn.connect.assert_awaited_once()


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

class TestStream:
    @pytest.mark.asyncio
    async def test_stream_sends_stream_command(self):
        fake_dev = _fake_device()
        with patch("qsense_ble.BleakClient") as MockClient:
            mock_conn = AsyncMock()
            mock_conn.is_connected = True
            mock_conn.connect = AsyncMock()
            mock_conn.start_notify = AsyncMock()
            mock_conn.write_gatt_char = AsyncMock()
            MockClient.return_value = mock_conn

            client = QSenseBleClient()
            client._device = fake_dev
            client._client = mock_conn

            await client.start_streaming()

            mock_conn.write_gatt_char.assert_awaited()
            # The write should contain a stream command
            args = mock_conn.write_gatt_char.call_args
            written_data = args[0][1]
            assert written_data[0] == CoreInterfaceParser.Opcode.Stream

    @pytest.mark.asyncio
    async def test_stop_streaming_sends_abort(self):
        fake_dev = _fake_device()
        with patch("qsense_ble.BleakClient") as MockClient:
            mock_conn = AsyncMock()
            mock_conn.is_connected = True
            mock_conn.write_gatt_char = AsyncMock()
            MockClient.return_value = mock_conn

            client = QSenseBleClient()
            client._device = fake_dev
            client._client = mock_conn

            await client.stop_streaming()

            mock_conn.write_gatt_char.assert_awaited()
            args = mock_conn.write_gatt_char.call_args
            written_data = args[0][1]
            assert written_data[0] == CoreInterfaceParser.Opcode.Abort


# ---------------------------------------------------------------------------
# Notification callback
# ---------------------------------------------------------------------------

class TestNotificationHandling:
    def test_notification_callback_parses_stream_packet(self):
        client = QSenseBleClient()
        received = []
        client.on_stream_data = lambda frame: received.append(frame)

        notification = _make_stream_notification(mode=1, buffering=1)
        # Simulate bleak notification — sender is the characteristic handle
        client._notification_handler(None, notification)

        assert len(received) == 1
        assert "header" in received[0]
        assert "samples" in received[0]


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect(self):
        with patch("qsense_ble.BleakClient") as MockClient:
            mock_conn = AsyncMock()
            mock_conn.disconnect = AsyncMock()
            MockClient.return_value = mock_conn

            client = QSenseBleClient()
            client._client = mock_conn
            await client.disconnect()
            mock_conn.disconnect.assert_awaited_once()
