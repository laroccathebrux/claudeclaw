# tests/test_router_native_intents.py
import pytest
from unittest.mock import MagicMock
from claudeclaw.core.event import Event
from claudeclaw.core.router import route


def _make_registry(skill_names: list[str]):
    """Build a mock registry that returns a mock skill for known names."""
    registry = MagicMock()

    def fake_find(name):
        if name in skill_names:
            skill = MagicMock()
            skill.name = name
            return skill
        return None

    registry.find.side_effect = fake_find
    return registry


@pytest.mark.parametrize("text", [
    "teach me to automate invoices",
    "I want to automate my report",
    "map this process",
    "pop",
    "procedimento",
    "how to send emails",
    "ensina como fazer relatório",
])
def test_pop_keywords_route_to_pop(text):
    registry = _make_registry(["pop"])
    event = Event(text=text, channel="telegram")
    skill = route(event, registry)
    assert skill.name == "pop"


@pytest.mark.parametrize("text", [
    "create an agent for invoicing",
    "i need someone to handle my emails",
    "crie um agente para meu ERP",
])
def test_agent_creator_keywords_route_to_agent_creator(text):
    registry = _make_registry(["agent-creator"])
    event = Event(text=text, channel="telegram")
    skill = route(event, registry)
    assert skill.name == "agent-creator"


def test_generic_text_does_not_match_native_intents(mocker):
    """Text with no known intent keywords falls through to general routing."""
    registry = _make_registry(["pop", "agent-creator"])
    event = Event(text="hello, what time is it?", channel="cli")
    mock_general = mocker.patch("claudeclaw.core.router._general_route", return_value=MagicMock(name="time-skill"))
    route(event, registry)
    mock_general.assert_called_once_with(event, registry)
