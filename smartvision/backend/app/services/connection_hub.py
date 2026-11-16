"""
SmartVision - WebSocket Connection Hub
Manages bi-directional WebSocket connections for the ESP32-S3 firmware (/ws/device)
and multiple frontend operator dashboards (/ws/client).
Enforces 20 Hz client rate limiting, envelope framing, and concurrent broadcasting.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings

logger = logging.getLogger("SmartVision.ConnectionHub")


class ConnectionHub:
    """
    Central switchboard routing messages between the PC backend,
    the embedded ESP32-S3 controller, and web operator dashboards.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self.device_ws: Optional[WebSocket] = None
        self.client_sockets: Set[WebSocket] = set()
        self._client_last_cmd_time: Dict[WebSocket, float] = {}
        self._seq = 0

    @property
    def is_device_connected(self) -> bool:
        """Returns True if an active ESP32 WebSocket session is registered."""
        return self.device_ws is not None

    @property
    def client_count(self) -> int:
        """Returns number of active operator frontend connections."""
        return len(self.client_sockets)

    def next_seq(self) -> int:
        """Generates monotonically increasing sequence number."""
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return self._seq

    def create_envelope(
        self,
        msg_type: str,
        payload: Dict[str, Any],
        corr_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Constructs authoritative 5-field JSON envelope from the backend."""
        return {
            "type": msg_type,
            "timestamp": int(time.time() * 1000),
            "sender": "backend",
            "seq": self.next_seq(),
            "corr_id": corr_id,
            "payload": payload,
        }

    async def register_device(self, websocket: WebSocket) -> None:
        """Registers connected ESP32-S3 device."""
        async with self._lock:
            if self.device_ws is not None and self.device_ws != websocket:
                try:
                    await self.device_ws.close(code=1000, reason="Replaced by new device connection")
                except Exception:
                    pass
            self.device_ws = websocket
            logger.info("ESP32-S3 registered on /ws/device")

    async def unregister_device(self, websocket: WebSocket) -> None:
        """Unregisters disconnected ESP32-S3 device."""
        async with self._lock:
            if self.device_ws == websocket:
                self.device_ws = None
                logger.info("ESP32-S3 unregistered from /ws/device")

    async def register_client(self, websocket: WebSocket) -> None:
        """Registers a new frontend operator dashboard."""
        async with self._lock:
            self.client_sockets.add(websocket)
            self._client_last_cmd_time[websocket] = 0.0
            logger.info(f"Frontend operator registered on /ws/client (total clients: {len(self.client_sockets)})")

    async def unregister_client(self, websocket: WebSocket) -> None:
        """Removes a disconnected frontend operator dashboard."""
        async with self._lock:
            self.client_sockets.discard(websocket)
            self._client_last_cmd_time.pop(websocket, None)
            logger.info(f"Frontend operator disconnected (remaining: {len(self.client_sockets)})")

    def check_client_rate_limit(self, websocket: WebSocket) -> bool:
        """
        Enforces 20 Hz (50 ms interval) client command rate limiting.
        Returns True if command is allowed, False if throttled.
        """
        now = time.time()
        last_time = self._client_last_cmd_time.get(websocket, 0.0)
        if now - last_time < settings.CLIENT_MIN_INTERVAL_S:
            return False
        self._client_last_cmd_time[websocket] = now
        return True

    async def send_to_device(self, msg: Dict[str, Any]) -> bool:
        """Dispatches an envelope directly to the ESP32-S3 device."""
        ws = self.device_ws
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(msg))
            return True
        except Exception as e:
            logger.warning(f"Error sending to ESP32: {e}")
            await self.unregister_device(ws)
            return False

    async def send_to_client(self, websocket: WebSocket, msg: Dict[str, Any]) -> bool:
        """Sends an envelope to a specific client."""
        try:
            await websocket.send_text(json.dumps(msg))
            return True
        except Exception:
            await self.unregister_client(websocket)
            return False

    async def broadcast_to_clients(self, msg: Dict[str, Any]) -> None:
        """Broadcasts an envelope to all connected frontend clients concurrently."""
        if not self.client_sockets:
            return

        msg_str = json.dumps(msg)
        dead_sockets = set()

        async def _send_safe(ws: WebSocket):
            try:
                await ws.send_text(msg_str)
            except Exception:
                dead_sockets.add(ws)

        await asyncio.gather(
            *[_send_safe(ws) for ws in list(self.client_sockets)],
            return_exceptions=True,
        )

        if dead_sockets:
            async with self._lock:
                for ws in dead_sockets:
                    self.client_sockets.discard(ws)
                    self._client_last_cmd_time.pop(ws, None)
