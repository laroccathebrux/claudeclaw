import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.core.event import Event, Response
from claudeclaw.core.conversation import ConversationStore, ConversationState
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.subagent.dispatch import DispatchResult


@pytest.fixture
def agent_creator_skill():
    return SkillManifest(
        name="agent-creator",
        description="Creates a new agent via a wizard",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Agent Creator\nYou are running the agent creation wizard.",
    )


@pytest.mark.asyncio
async def test_orchestrator_resumes_active_conversation(agent_creator_skill, tmp_path, monkeypatch):
    """When an active conversation exists, orchestrator bypasses router and uses conversation skill."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()

    conv_store = ConversationStore()
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=2, data={"task_description": "issue invoices"},
        history=[{"role": "assistant", "content": "What do you need?"}],
    )
    conv_store.save(state)

    mock_adapter = AsyncMock()
    mock_adapter.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.find.return_value = agent_creator_skill
    mock_registry.list_skills.return_value = [agent_creator_skill]

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="Which systems?", skill_name="agent-creator", stop_reason="end_turn"
    )

    event = Event(text="ERP and Gmail", channel="cli", user_id="local", channel_adapter=mock_adapter)

    with patch("claudeclaw.core.orchestrator.SubagentDispatcher", return_value=mock_dispatcher):
        orchestrator = Orchestrator(
            skill_registry=mock_registry,
            credential_store=MagicMock(),
            conv_store=conv_store,
        )
        queue = asyncio.Queue()
        await queue.put(event)
        await queue.put(None)  # sentinel

        with patch("claudeclaw.core.orchestrator.route_event") as mock_route:
            await orchestrator.run(queue, stop_sentinel=True)
            # Router should NOT have been called — conversation was active
            mock_route.assert_not_called()

    mock_dispatcher.dispatch.assert_called_once()
    # Verify dispatch was called with conversation kwarg
    call_kwargs = mock_dispatcher.dispatch.call_args
    assert call_kwargs.kwargs.get("conversation") is not None or \
           (len(call_kwargs.args) >= 3 and call_kwargs.args[2] is not None)


@pytest.mark.asyncio
async def test_orchestrator_uses_route_when_no_active_conversation(agent_creator_skill, tmp_path, monkeypatch):
    """When no active conversation, orchestrator uses route_event as normal."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()

    conv_store = ConversationStore()

    mock_adapter = AsyncMock()
    mock_adapter.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [agent_creator_skill]

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="What do you need?", skill_name="agent-creator", stop_reason="end_turn"
    )

    event = Event(text="create an agent for invoices", channel="cli", user_id="local", channel_adapter=mock_adapter)

    with patch("claudeclaw.core.orchestrator.SubagentDispatcher", return_value=mock_dispatcher), \
         patch("claudeclaw.core.orchestrator.route_event", return_value=agent_creator_skill) as mock_route:
        orchestrator = Orchestrator(
            skill_registry=mock_registry,
            credential_store=MagicMock(),
            conv_store=conv_store,
        )
        queue = asyncio.Queue()
        await queue.put(event)
        await queue.put(None)  # sentinel
        await orchestrator.run(queue, stop_sentinel=True)

    mock_route.assert_called_once()


def test_dispatcher_prepends_conversation_history():
    """Dispatcher passes conversation history as prior messages to Claude."""
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.core.conversation import ConversationState
    from claudeclaw.skills.loader import SkillManifest
    from claudeclaw.core.event import Event
    from unittest.mock import MagicMock, patch

    skill = SkillManifest(
        name="agent-creator",
        description="wizard",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Agent Creator\nRun the wizard.",
    )
    event = Event(text="ERP and Gmail", channel="cli", user_id="local")
    history = [
        {"role": "assistant", "content": "What do you need?"},
        {"role": "user", "content": "issue invoices"},
    ]
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=2, data={}, history=history,
    )

    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Which systems?")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill, event, conversation=state)

    messages_arg = mock_create.call_args.kwargs["messages"]
    # History should appear before the current user message
    assert messages_arg[0]["role"] == "assistant"
    assert messages_arg[1]["role"] == "user"
    assert messages_arg[1]["content"] == "issue invoices"
    assert messages_arg[-1]["content"] == "ERP and Gmail"
