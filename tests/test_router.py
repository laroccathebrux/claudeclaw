import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.core.router import Router
from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def skills():
    return [
        SkillManifest(
            name="invoice-agent",
            description="Emits invoices and sends them by email at month end",
            trigger="cron",
            schedule="0 0 28 * *",
            autonomy="autonomous",
            shell_policy="none",
            body="...",
        ),
        SkillManifest(
            name="crm-followup",
            description="Sends follow-up messages to hot CRM leads",
            trigger="on-demand",
            autonomy="notify",
            shell_policy="none",
            body="...",
        ),
    ]


def test_router_returns_best_matching_skill(skills):
    router = Router(skills)
    event = Event(text="I need to follow up with my leads", channel="cli")

    with patch.object(router, "_match_with_claude", return_value="crm-followup"):
        result = router.route(event)

    assert result is not None
    assert result.name == "crm-followup"


def test_router_returns_none_when_no_match(skills):
    router = Router(skills)
    event = Event(text="what is the weather today", channel="cli")

    with patch.object(router, "_match_with_claude", return_value=None):
        result = router.route(event)

    assert result is None


def test_router_returns_none_on_empty_skill_list():
    router = Router([])
    event = Event(text="do something", channel="cli")
    result = router.route(event)
    assert result is None
