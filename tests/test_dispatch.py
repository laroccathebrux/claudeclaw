# tests/test_dispatch.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.subagent.dispatch import SubagentDispatcher, DispatchResult
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event


@pytest.fixture
def skill():
    return SkillManifest(
        name="test-skill",
        description="Test skill",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Test\nYou are a helpful test agent. Echo back what the user says.",
        tools=[],
        credentials=[],
    )


@pytest.fixture
def event():
    return Event(text="hello", channel="cli", user_id="local")


def test_dispatch_returns_result_text(skill, event):
    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Echo: hello")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response):
        result = dispatcher.dispatch(skill, event)

    assert isinstance(result, DispatchResult)
    assert result.text == "Echo: hello"
    assert result.skill_name == "test-skill"


def test_dispatch_uses_skill_body_as_system_prompt(skill, event):
    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill, event)

    call_kwargs = mock_create.call_args.kwargs
    assert skill.body in call_kwargs["system"]


def test_dispatch_enforces_tool_permission(skill, event):
    """A skill with no tools declared should receive an empty tools list."""
    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill, event)

    call_kwargs = mock_create.call_args.kwargs
    # No tools declared in skill → tools list not passed (or empty)
    assert call_kwargs.get("tools", []) == []


def test_dispatch_injects_credentials_as_context(skill, event, tmp_path, monkeypatch):
    """Credentials should be injected into system prompt context."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skill.credentials = ["erp-user"]

    from claudeclaw.auth.keyring import CredentialStore
    store = CredentialStore(backend="file", master_password="test")
    store.set("erp-user", "alice")

    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        with patch("claudeclaw.subagent.dispatch.CredentialStore", return_value=store):
            dispatcher.dispatch(skill, event)

    system_prompt = mock_create.call_args.kwargs["system"]
    assert "alice" in system_prompt
