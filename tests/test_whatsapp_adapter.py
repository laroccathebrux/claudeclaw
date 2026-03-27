# tests/test_whatsapp_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.channels.whatsapp_adapter import WhatsAppAdapter
from claudeclaw.core.event import Event, Response


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get.side_effect = lambda key: {
        "twilio-account-sid": "ACtest123",
        "twilio-auth-token": "authtoken456",
        "twilio-whatsapp-from": "+14155238886",
    }.get(key)
    return store


@pytest.fixture
def adapter(mock_store):
    return WhatsAppAdapter(credential_store=mock_store)


def test_adapter_channel_name(adapter):
    assert adapter.channel_name == "whatsapp"


@pytest.mark.asyncio
async def test_inbound_webhook_builds_event(adapter):
    form_data = {
        "From": "whatsapp:+15551234567",
        "To": "whatsapp:+14155238886",
        "Body": "Hello agent",
        "MessageSid": "SMxxx",
    }
    event = await adapter._parse_twilio_payload(form_data)
    assert event.channel == "whatsapp"
    assert event.user_id == "whatsapp:+15551234567"
    assert event.text == "Hello agent"
    assert event.raw["MessageSid"] == "SMxxx"


@pytest.mark.asyncio
async def test_invalid_signature_raises(adapter):
    with patch.object(adapter, "_validate_signature", return_value=False):
        with pytest.raises(PermissionError, match="Invalid Twilio signature"):
            await adapter.handle_inbound_raw(
                form_data={"From": "whatsapp:+15551234567", "Body": "hi"},
                signature="bad",
                url="https://example.com/whatsapp/inbound",
            )


@pytest.mark.asyncio
async def test_send_calls_twilio_api(adapter):
    response = Response(
        channel="whatsapp",
        user_id="whatsapp:+15551234567",
        text="Hello back",
        event=MagicMock(),
    )
    with patch("claudeclaw.channels.whatsapp_adapter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=201)
        await adapter.send(response)

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "ACtest123" in call_kwargs[0][0]
    assert call_kwargs[1]["data"]["To"] == "whatsapp:+15551234567"
    assert call_kwargs[1]["data"]["Body"] == "Hello back"


@pytest.mark.asyncio
async def test_send_uses_correct_from_number(adapter):
    response = Response(
        channel="whatsapp",
        user_id="whatsapp:+15551234567",
        text="Hi",
        event=MagicMock(),
    )
    with patch("claudeclaw.channels.whatsapp_adapter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=201)
        await adapter.send(response)

    data = mock_client.post.call_args[1]["data"]
    assert data["From"] == "whatsapp:+14155238886"
