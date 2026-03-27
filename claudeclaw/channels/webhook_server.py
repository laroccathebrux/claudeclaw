# claudeclaw/channels/webhook_server.py
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)

app = FastAPI(title="ClaudeClaw Webhook Server")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def register_route(method: str, path: str, handler: Callable, **kwargs) -> None:
    """Register a route on the shared FastAPI app at runtime."""
    app.add_api_route(path, handler, methods=[method.upper()], **kwargs)


def register_websocket_route(path: str, handler: Callable) -> None:
    """Register a WebSocket route on the shared FastAPI app."""
    app.add_websocket_route(path, handler)


_server_task: asyncio.Task | None = None


async def start_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the uvicorn server. Call after all routes have been registered."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"Webhook server starting on {host}:{port}")
    await server.serve()


async def start_server_background(host: str = "0.0.0.0", port: int = 8080) -> asyncio.Task:
    """Launch the webhook server as a background asyncio task."""
    global _server_task
    _server_task = asyncio.create_task(start_server(host=host, port=port))
    return _server_task
