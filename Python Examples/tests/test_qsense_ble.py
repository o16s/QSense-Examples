import struct
import pytest
import asyncio
import sys
import os
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
    # Set a timestamp so per-sample timestamps are testable
    struct.pack_into("<I", payload, 1, 1000)
    struct.pack_into("<H", payload, 5, 0)
    # acc_range=0, gyr_range=0
    payload[9] = 0x00
    # Write raw samples (9 × int16 each)
    for j in range(buffering):
        for i in range(9):
            struct.pack_into("<h", payload, 10 + j * 18 + i * 2, (i + 1) * 100)
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

    @pytest.mark.asyncio
    async def test_connect_with_explicit_device(self):
        """connect(device=...) should use the supplied device, not _device."""
        fake_dev_a = _fake_device(name="QSense-A", address="AA:AA:AA:AA:AA:AA")
        fake_dev_b = _fake_device(name="QSense-B", address="BB:BB:BB:BB:BB:BB")
        with patch("qsense_ble.BleakClient") as MockClient:
            mock_conn = AsyncMock()
            mock_conn.connect = AsyncMock()
            mock_conn.start_notify = AsyncMock()
            MockClient.return_value = mock_conn

            client = QSenseBleClient()
            client._device = fake_dev_a  # scan stored device A
            await client.connect(device=fake_dev_b)  # but we explicitly pass B
            MockClient.assert_called_once_with(fake_dev_b)

    @pytest.mark.asyncio
    async def test_connect_no_device_raises(self):
        """connect() without prior scan and no explicit device should raise."""
        client = QSenseBleClient()
        with pytest.raises(RuntimeError, match="No device found"):
            await client.connect()


# ---------------------------------------------------------------------------
# Multi-device
# ---------------------------------------------------------------------------

class TestMultiDevice:
    @pytest.mark.asyncio
    async def test_two_clients_connect_to_different_devices(self):
        """Two independent clients can connect to two different devices."""
        dev_a = _fake_device(name="QSense-A", address="AA:AA:AA:AA:AA:AA")
        dev_b = _fake_device(name="QSense-B", address="BB:BB:BB:BB:BB:BB")

        with patch("qsense_ble.BleakClient") as MockClient:
            mock_conn_a = AsyncMock()
            mock_conn_a.connect = AsyncMock()
            mock_conn_a.start_notify = AsyncMock()
            mock_conn_a.disconnect = AsyncMock()

            mock_conn_b = AsyncMock()
            mock_conn_b.connect = AsyncMock()
            mock_conn_b.start_notify = AsyncMock()
            mock_conn_b.disconnect = AsyncMock()

            MockClient.side_effect = [mock_conn_a, mock_conn_b]

            client_a = QSenseBleClient()
            client_b = QSenseBleClient()

            await client_a.connect(device=dev_a)
            await client_b.connect(device=dev_b)

            # Each client got its own BleakClient with the correct device
            calls = MockClient.call_args_list
            assert calls[0][0][0] is dev_a
            assert calls[1][0][0] is dev_b

            # Each client has an independent connection
            mock_conn_a.connect.assert_awaited_once()
            mock_conn_b.connect.assert_awaited_once()

            await client_a.disconnect()
            await client_b.disconnect()
            mock_conn_a.disconnect.assert_awaited_once()
            mock_conn_b.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_two_clients_receive_independent_notifications(self):
        """Notifications on one client do not leak to the other."""
        dev_a = _fake_device(name="QSense-A", address="AA:AA:AA:AA:AA:AA")
        dev_b = _fake_device(name="QSense-B", address="BB:BB:BB:BB:BB:BB")

        client_a = QSenseBleClient()
        client_b = QSenseBleClient()

        received_a: list = []
        received_b: list = []
        client_a.on_stream_data = lambda frame: received_a.append(frame)
        client_b.on_stream_data = lambda frame: received_b.append(frame)

        notification = _make_stream_notification(mode=1, buffering=1)

        # Only client_a receives a notification
        client_a._notification_handler(None, notification)
        assert len(received_a) == 1
        assert len(received_b) == 0


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

    def test_notification_with_sampling_rate_adds_timestamps(self):
        client = QSenseBleClient(sampling_rate=200)
        received = []
        client.on_stream_data = lambda frame: received.append(frame)

        notification = _make_stream_notification(mode=1, buffering=3)
        client._notification_handler(None, notification)

        assert len(received) == 1
        samples = received[0]["samples"]
        assert len(samples) == 3
        # Each sample should have a timestamp
        for s in samples:
            assert "timestamp" in s

    def test_default_sampling_rate_is_none(self):
        client = QSenseBleClient()
        assert client.sampling_rate is None

    def test_sampling_rate_can_be_set(self):
        client = QSenseBleClient(sampling_rate=200)
        assert client.sampling_rate == 200

    def test_sampling_rate_at_max_is_valid(self):
        client = QSenseBleClient(sampling_rate=800)
        assert client.sampling_rate == 800

    def test_sampling_rate_exceeding_max_raises(self):
        with pytest.raises(ValueError, match="exceeds the maximum"):
            QSenseBleClient(sampling_rate=801)


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
