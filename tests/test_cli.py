from click.testing import CliRunner
from claudeclaw.cli import main
from unittest.mock import patch, MagicMock


def test_login_command_calls_auth_manager():
    runner = CliRunner()
    with patch("claudeclaw.cli.AuthManager") as MockAuth:
        mock_instance = MagicMock()
        MockAuth.return_value = mock_instance
        result = runner.invoke(main, ["login"])
    mock_instance.login.assert_called_once()
    assert result.exit_code == 0


def test_skills_list_command_prints_skills(tmp_path, monkeypatch):
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    # Create a fake skill
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-skill.md").write_text("""---
name: my-skill
description: Does something useful
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
Body""")
    runner = CliRunner()
    result = runner.invoke(main, ["skills", "list"])
    assert "my-skill" in result.output
    assert result.exit_code == 0
    get_settings.cache_clear()


def test_start_command_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert "start" in result.output


def test_agents_run_command_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["agents", "--help"])
    assert "run" in result.output
