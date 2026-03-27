# claudeclaw/channels/whatsapp_adapter.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import Response as FastAPIResponse
from twilio.request_validator import RequestValidator

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)

_TWILIO_MESSAGES_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
)


class WhatsAppAdapter(ChannelAdapter):
    """Channel adapter for WhatsApp via Twilio."""

    channel_name = "whatsapp"

    def __init__(self, credential_store, event_queue: asyncio.Queue | None = None):
        self._store = credential_store
        self._queue: asyncio.Queue[Event] = event_queue or asyncio.Queue()

    async def receive(self):
        """WhatsApp is webhook-driven; events arrive via handle_inbound, not receive()."""
        # Yield from the queue — allows use with receive()-based manager
        while True:
            event = await self._queue.get()
            yield event

    async def start(self) -> None:
        """Keep adapter alive; events arrive via HTTP webhook."""
        logger.info("WhatsApp adapter ready (webhook-driven)")
        await asyncio.Event().wait()

    async def send(self, response: Response) -> None:
        account_sid = self._store.get("twilio-account-sid")
        auth_token = self._store.get("twilio-auth-token")
        from_number = self._store.get("twilio-whatsapp-from")

        url = _TWILIO_MESSAGES_URL.format(account_sid=account_sid)
        payload = {
            "From": f"whatsapp:{from_number}",
            "To": response.user_id,
            "Body": response.text,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                data=payload,
                auth=(account_sid, auth_token),
            )
            if resp.status_code >= 400:
                logger.error("Twilio send failed: %s %s", resp.status_code, resp.text)

    async def handle_inbound(self, request: Request) -> FastAPIResponse:
        """FastAPI endpoint for POST /whatsapp/inbound."""
        form_data = dict(await request.form())
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)

        if not self._validate_signature(signature, url, form_data):
            logger.warning("Invalid Twilio signature from %s", request.client)
            return FastAPIResponse(content="Forbidden", status_code=403)

        event = await self._parse_twilio_payload(form_data)
        await self._queue.put(event)
        return FastAPIResponse(
            content='<?xml version="1.0"?><Response></Response>',
            media_type="text/xml",
            status_code=200,
        )

    async def handle_inbound_raw(
        self,
        form_data: dict[str, str],
        signature: str,
        url: str,
    ) -> Event:
        """Testable version: validate + parse without HTTP request object."""
        if not self._validate_signature(signature, url, form_data):
            raise PermissionError("Invalid Twilio signature")
        return await self._parse_twilio_payload(form_data)

    def _validate_signature(self, signature: str, url: str, params: dict) -> bool:
        auth_token = self._store.get("twilio-auth-token")
        if not auth_token:
            return False
        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)

    async def _parse_twilio_payload(self, form_data: dict[str, Any]) -> Event:
        return Event(
            channel=self.channel_name,
            user_id=form_data["From"],
            text=form_data.get("Body", ""),
            raw=dict(form_data),
        )
