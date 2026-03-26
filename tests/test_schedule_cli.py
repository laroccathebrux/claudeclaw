import pytest
import yaml
from click.testing import CliRunner
from claudeclaw.cli import main


@pytest.fixture
def populated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    schedules = {
        "erp-invoices": {
            "cron_id": "cron_abc123",
            "schedule": "0 0 28 * *",
            "registered_at": "2026-03-25T10:00:00Z",
        },
    }
    (config_dir / "schedules.yaml").write_text(yaml.dump(schedules))

    triggers = {
        "new-crm-lead": {
            "skill_name": "crm-followup",
            "webhook_url": "https://hooks.anthropic.com/rt/xyz789",
            "registered_at": "2026-03-25T10:00:01Z",
        },
    }
    (config_dir / "triggers.yaml").write_text(yaml.dump(triggers))
    return tmp_path


def test_schedule_list_shows_cron(populated_config):
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "list"])
    assert result.exit_code == 0
    assert "erp-invoices" in result.output
    assert "0 0 28 * *" in result.output


def test_schedule_list_shows_webhook(populated_config):
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "list"])
    assert result.exit_code == 0
    assert "new-crm-lead" in result.output
    assert "crm-followup" in result.output


def test_schedule_list_empty_shows_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "list"])
    assert result.exit_code == 0
    assert "No" in result.output or "empty" in result.output.lower()


def test_schedule_run_fires_skill(populated_config, monkeypatch, tmp_path):
    """schedule run should invoke the subagent for the named skill."""
    from unittest.mock import AsyncMock, patch, MagicMock
    from claudeclaw.skills.loader import SkillManifest

    # We need a skill in the registry for "erp-invoices"
    # Mock the registry to return a skill
    fake_skill = SkillManifest(
        name="erp-invoices",
        description="Send invoices",
        trigger="cron",
        schedule="0 0 28 * *",
        autonomy="autonomous",
        shell_policy="none",
        body="Send invoices.",
    )

    runner = CliRunner()
    with patch("claudeclaw.cli.dispatch_skill", new_callable=AsyncMock) as mock_dispatch, \
         patch("claudeclaw.cli.SkillRegistry") as MockRegistry:
        mock_registry_instance = MagicMock()
        mock_registry_instance.find.return_value = fake_skill
        MockRegistry.return_value = mock_registry_instance
        mock_dispatch.return_value = MagicMock(text="Done.")
        result = runner.invoke(main, ["schedule", "run", "erp-invoices"])

    assert result.exit_code == 0
    assert "erp-invoices" in result.output


def test_schedule_run_unknown_skill_exits_nonzero(populated_config, monkeypatch):
    from unittest.mock import patch, MagicMock

    runner = CliRunner()
    with patch("claudeclaw.cli.SkillRegistry") as MockRegistry:
        mock_registry_instance = MagicMock()
        mock_registry_instance.find.return_value = None
        MockRegistry.return_value = mock_registry_instance
        result = runner.invoke(main, ["schedule", "run", "skill-that-does-not-exist"])

    assert result.exit_code != 0
