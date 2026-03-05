"""
qsense_ble — Async BLE client for QSense 9DOF IMU sensors using bleak.

Provides scanning, connecting, streaming, and disconnecting from a QSense
sensor over Bluetooth Low Energy.  Designed for Raspberry Pi (CM4 or similar)
with on-board Bluetooth — no dongle required.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from bleak import BleakClient, BleakScanner

from qsense_parser import CoreInterfaceParser, parse_stream_payload


# Nordic UART Service UUIDs
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host → sensor (write)
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # sensor → host (notify)

QSENSE_NAME = "qsense"


class QSenseBleClient:
    """High-level async client for a single QSense sensor.

    Parameters
    ----------
    sampling_rate : float or None
        Sensor sampling rate in Hz (e.g. 200).  When set, each sample in a
        buffered stream packet receives an interpolated per-sample timestamp.
    """

    def __init__(self, sampling_rate: float | None = None) -> None:
        self._device: Any | None = None
        self._client: BleakClient | None = None
        if sampling_rate is not None and sampling_rate > CoreInterfaceParser.MAX_SAMPLING_RATE:
            raise ValueError(
                f"sampling_rate {sampling_rate} Hz exceeds the maximum "
                f"supported rate of {CoreInterfaceParser.MAX_SAMPLING_RATE} Hz"
            )
        self.sampling_rate: float | None = sampling_rate
        self.on_stream_data: Callable[[dict[str, Any]], None] | None = None

    # -- Scanning ----------------------------------------------------------

    async def scan(self, timeout: float = 5.0) -> list[Any]:
        """Scan for nearby QSense devices and return matching BLE devices."""
        scanner = BleakScanner()
        devices = await scanner.discover(timeout=timeout)
        qsense_devices = [
            d for d in devices
            if d.name and d.name.lower().startswith(QSENSE_NAME)
        ]
        if qsense_devices:
            self._device = qsense_devices[0]
        return qsense_devices

    # -- Connection --------------------------------------------------------

    async def connect(self, device: Any | None = None) -> None:
        """Connect to a QSense device and subscribe to TX notifications.

        Parameters
        ----------
        device : BLE device object or None
            A specific device returned by :meth:`scan`.  When *None*, the
            first device discovered during the last :meth:`scan` call is used.
        """
        target = device if device is not None else self._device
        if target is None:
            raise RuntimeError("No device found. Call scan() first or pass a device.")
        self._device = target
        self._client = BleakClient(target)
        await self._client.connect()
        await self._client.start_notify(NUS_TX_UUID, self._notification_handler)

    # -- Streaming ---------------------------------------------------------

    async def start_streaming(self) -> None:
        """Send the Stream command to begin receiving IMU data."""
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        cmd = CoreInterfaceParser.create_stream_packet()
        await self._client.write_gatt_char(NUS_RX_UUID, cmd)

    async def stop_streaming(self) -> None:
        """Send the Abort command to stop streaming."""
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        cmd = CoreInterfaceParser.create_abort_packet()
        await self._client.write_gatt_char(NUS_RX_UUID, cmd)

    async def stream(self, duration: float = 10.0):
        """Async generator that yields parsed stream frames for *duration* seconds."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        original_cb = self.on_stream_data
        self.on_stream_data = lambda frame: queue.put_nowait(frame)

        await self.start_streaming()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration
        try:
            while loop.time() < deadline:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield frame
                except asyncio.TimeoutError:
                    continue
        finally:
            await self.stop_streaming()
            self.on_stream_data = original_cb

    # -- Reading memory ----------------------------------------------------

    async def read_memory(self, address: int = 0x00000000, length: int = 0x40) -> None:
        """Send a Read command to request control memory."""
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        cmd = CoreInterfaceParser.create_read_packet(address, length)
        await self._client.write_gatt_char(NUS_RX_UUID, cmd)

    # -- Disconnect --------------------------------------------------------

    async def disconnect(self) -> None:
        """Disconnect from the sensor."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    # -- Internal ----------------------------------------------------------

    def _notification_handler(self, sender: Any, data: bytes) -> None:
        """Called by bleak for every TX notification."""
        parsed = CoreInterfaceParser.parse_packet(data, sampling_rate=self.sampling_rate)
        if parsed is not None and self.on_stream_data is not None:
            self.on_stream_data(parsed)
