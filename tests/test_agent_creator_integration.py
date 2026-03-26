# tests/test_agent_creator_integration.py
"""
Integration test: simulates a full multi-turn Agent Creator wizard.
Uses mock Claude SDK responses — no real API calls.
"""
import pytest
from pathlib import Path
from claudeclaw.core.conversation import ConversationStore, ConversationState
from claudeclaw.skills.generator import SkillGenerator, WizardOutput
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.skills.loader import load_skill


@pytest.fixture
def skills_env(tmp_path, monkeypatch):
    """Set up isolated environment with temporary skills and conversation directories."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    conv_dir = tmp_path / "config" / "conversations"
    conv_dir.mkdir(parents=True)
    return {
        "home": tmp_path,
        "skills_dir": skills_dir,
        "conv_dir": conv_dir,
    }


def test_wizard_output_produces_valid_loadable_skill(skills_env):
    """A WizardOutput fed to SkillGenerator produces a skill that passes load_skill()."""
    generator = SkillGenerator(skills_dir=skills_env["skills_dir"])
    output = WizardOutput(
        task_description="Issue monthly invoices from ERP and email clients",
        systems=["erp", "gmail"],
        credentials=["inv-erp-user", "inv-erp-token", "inv-gmail-token"],
        trigger="cron",
        schedule="0 0 28 * *",
        autonomy="autonomous",
    )
    path = generator.generate(output)
    skill = load_skill(path)
    assert skill.name is not None
    assert skill.trigger == "cron"
    assert skill.schedule == "0 0 28 * *"
    assert skill.autonomy == "autonomous"
    assert set(skill.credentials) == {"inv-erp-user", "inv-erp-token", "inv-gmail-token"}


def test_generated_skill_is_immediately_findable_via_registry(skills_env):
    """After generating a skill, SkillRegistry.find() returns it without restart."""
    generator = SkillGenerator(skills_dir=skills_env["skills_dir"])
    registry = SkillRegistry(skills_dir=skills_env["skills_dir"])

    output = WizardOutput(
        task_description="Send weekly CRM follow-up emails",
        systems=["crm"],
        credentials=["crm-followup-crm-token"],
        trigger="cron",
        schedule="0 9 * * 1",
        autonomy="notify",
    )
    path = generator.generate(output)

    # Reload and find
    registry.reload()
    skill = registry.find(path.stem)
    assert skill is not None
    assert skill.name == path.stem


def test_conversation_state_lifecycle(skills_env):
    """ConversationStore correctly saves, retrieves, and clears wizard state."""
    store = ConversationStore(base_dir=skills_env["conv_dir"])

    assert not store.has_active("telegram", "user99")

    state = ConversationState(
        channel="telegram",
        user_id="user99",
        skill_name="agent-creator",
        step=1,
        data={},
        history=[{"role": "assistant", "content": "What do you need?"}],
    )
    store.save(state)
    assert store.has_active("telegram", "user99")

    loaded = store.get("telegram", "user99")
    loaded.step = 2
    loaded.data["task_description"] = "Issue invoices"
    loaded.history.append({"role": "user", "content": "Issue invoices"})
    store.save(loaded)

    reloaded = store.get("telegram", "user99")
    assert reloaded.step == 2
    assert reloaded.data["task_description"] == "Issue invoices"
    assert len(reloaded.history) == 2

    store.clear("telegram", "user99")
    assert not store.has_active("telegram", "user99")


def test_full_wizard_to_skill_pipeline(skills_env):
    """
    Simulate the complete wizard pipeline end-to-end:
    ConversationState accumulates data across turns → SkillGenerator produces skill.
    """
    store = ConversationStore(base_dir=skills_env["conv_dir"])
    generator = SkillGenerator(skills_dir=skills_env["skills_dir"])
    registry = SkillRegistry(skills_dir=skills_env["skills_dir"])

    # Turn 1: wizard starts
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    store.save(state)

    # Turn 2: user provides task description
    state = store.get("cli", "local")
    state.step = 2
    state.data["task_description"] = "Process new leads from CRM and send welcome email"
    state.history += [
        {"role": "assistant", "content": "What do you need the agent to do?"},
        {"role": "user", "content": "Process new leads from CRM and send welcome email"},
    ]
    store.save(state)

    # Turn 3: systems identified
    state = store.get("cli", "local")
    state.step = 3
    state.data["systems"] = ["crm", "gmail"]
    store.save(state)

    # Turn 4: credentials collected
    state = store.get("cli", "local")
    state.step = 4
    state.data["credentials"] = ["crm-welcome-crm-token", "crm-welcome-gmail-token"]
    store.save(state)

    # Turn 5: schedule set
    state = store.get("cli", "local")
    state.step = 5
    state.data["trigger"] = "on-demand"
    state.data["schedule"] = None
    store.save(state)

    # Turn 6: autonomy set
    state = store.get("cli", "local")
    state.step = 6
    state.data["autonomy"] = "notify"
    store.save(state)

    # Wizard complete: generate skill
    final_state = store.get("cli", "local")
    output = WizardOutput(
        task_description=final_state.data["task_description"],
        systems=final_state.data["systems"],
        credentials=final_state.data["credentials"],
        trigger=final_state.data["trigger"],
        schedule=final_state.data["schedule"],
        autonomy=final_state.data["autonomy"],
    )
    path = generator.generate(output)
    assert path.exists()

    skill = load_skill(path)
    assert "crm-welcome-crm-token" in skill.credentials
    assert skill.trigger == "on-demand"
    assert skill.autonomy == "notify"

    # Clear conversation
    store.clear("cli", "local")
    assert not store.has_active("cli", "local")

    # Skill is findable in registry
    registry.reload()
    found = registry.find(skill.name)
    assert found is not None
