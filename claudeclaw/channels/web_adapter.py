# claudeclaw/channels/web_adapter.py
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class WebAdapter(ChannelAdapter):
    """Channel adapter for the local Web UI (FastAPI + WebSocket)."""

    channel_name = "web"

    def __init__(self, port: int = 3000, event_queue: asyncio.Queue | None = None):
        self._port = port
        self._queue: asyncio.Queue[Event] = event_queue or asyncio.Queue()
        self._connections: dict[str, WebSocket] = {}

    # ------------------------------------------------------------------
    # ChannelAdapter ABC
    # ------------------------------------------------------------------

    async def receive(self) -> AsyncGenerator[Event, None]:
        """Events arrive via WebSocket; yield from queue."""
        while True:
            event = await self._queue.get()
            yield event

    async def start(self) -> None:
        self.register_routes()
        logger.info("Web UI adapter ready at http://localhost:%d", self._port)
        await asyncio.Event().wait()  # routes registered; server managed externally

    async def send(self, response: Response) -> None:
        conn_id = response.event.raw.get("connection_id")
        ws = self._connections.get(conn_id)
        if ws is None:
            logger.warning("WebSocket connection %s not found for send", conn_id)
            return
        await ws.send_text(response.text)

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def register_routes(self) -> None:
        from claudeclaw.channels.webhook_server import (
            register_route,
            register_websocket_route,
        )

        register_route("GET", "/", self._serve_index)
        register_websocket_route("/ws", self._websocket_endpoint)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _serve_index(self) -> HTMLResponse:
        index_path = _STATIC_DIR / "index.html"
        content = index_path.read_text(encoding="utf-8")
        return HTMLResponse(content=content)

    async def _websocket_endpoint(self, websocket: WebSocket) -> None:
        conn_id = str(uuid.uuid4())
        await websocket.accept()
        self._connections[conn_id] = websocket
        logger.info("WebSocket client connected: %s", conn_id)
        try:
            while True:
                data = await websocket.receive_text()
                await self._handle_text_message(data, conn_id)
        except WebSocketDisconnect:
            self._remove_connection(conn_id)
            logger.info("WebSocket client disconnected: %s", conn_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _handle_text_message(self, text: str, conn_id: str) -> None:
        event = Event(
            channel=self.channel_name,
            user_id="localhost",
            text=text,
            raw={"connection_id": conn_id},
        )
        await self._queue.put(event)

    def _remove_connection(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
