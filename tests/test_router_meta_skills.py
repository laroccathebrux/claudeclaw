import pytest
from unittest.mock import patch
from claudeclaw.core.router import Router
from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def no_skills_router():
    return Router([])


@pytest.fixture
def some_skills_router():
    return Router([
        SkillManifest(
            name="crm-followup",
            description="Send follow-up messages to hot CRM leads",
            trigger="on-demand",
            autonomy="notify",
            shell_policy="none",
            body="...",
        )
    ])


def test_router_returns_agent_creator_meta_skill(no_skills_router):
    event = Event(text="I want to create a new agent", channel="cli")
    with patch.object(no_skills_router, "_match_with_claude", return_value="agent-creator"):
        result = no_skills_router.route(event)
    assert result is not None
    assert result == "agent-creator"


def test_router_returns_pop_meta_skill(no_skills_router):
    event = Event(text="teach the system how to do this", channel="cli")
    with patch.object(no_skills_router, "_match_with_claude", return_value="pop"):
        result = no_skills_router.route(event)
    assert result == "pop"


def test_router_includes_meta_skills_in_prompt_even_with_empty_skills():
    router = Router([])
    prompt = router._build_routing_prompt("create an agent for me")
    assert "agent-creator" in prompt
    assert "pop" in prompt


def test_router_includes_meta_skills_alongside_installed_skills(some_skills_router):
    prompt = some_skills_router._build_routing_prompt("create an agent for me")
    assert "agent-creator" in prompt
    assert "crm-followup" in prompt


def test_router_returns_installed_skill_when_matched(some_skills_router):
    event = Event(text="follow up with my leads", channel="cli")
    with patch.object(some_skills_router, "_match_with_claude", return_value="crm-followup"):
        result = some_skills_router.route(event)
    assert result is not None
    assert hasattr(result, "name")
    assert result.name == "crm-followup"


def test_router_returns_none_on_no_match(some_skills_router):
    event = Event(text="what is the weather", channel="cli")
    with patch.object(some_skills_router, "_match_with_claude", return_value=None):
        result = some_skills_router.route(event)
    assert result is None
