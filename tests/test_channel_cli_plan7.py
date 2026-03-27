# tests/test_channel_cli_plan7.py
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from claudeclaw.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_channel_add_whatsapp_stores_credentials(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    with patch("claudeclaw.cli.CredentialStore") as MockStore:
        mock_store = MagicMock()
        MockStore.return_value = mock_store
        result = runner.invoke(main, [
            "channel", "add", "whatsapp",
            "--account-sid", "ACtest",
            "--auth-token", "token123",
            "--from", "+14155238886",
        ])
    assert result.exit_code == 0
    calls = {c[0][0]: c[0][1] for c in mock_store.set.call_args_list}
    assert calls["twilio-account-sid"] == "ACtest"
    assert calls["twilio-auth-token"] == "token123"
    assert calls["twilio-whatsapp-from"] == "+14155238886"


def test_channel_add_slack_stores_credentials(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    with patch("claudeclaw.cli.CredentialStore") as MockStore:
        mock_store = MagicMock()
        MockStore.return_value = mock_store
        result = runner.invoke(main, [
            "channel", "add", "slack",
            "--token", "xoxb-test",
            "--signing-secret", "secret123",
        ])
    assert result.exit_code == 0
    calls = {c[0][0]: c[0][1] for c in mock_store.set.call_args_list}
    assert calls["slack-bot-token"] == "xoxb-test"
    assert calls["slack-signing-secret"] == "secret123"


def test_channel_add_web_writes_config(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    result = runner.invoke(main, ["channel", "add", "web", "--port", "3000"])
    assert result.exit_code == 0
    channels_yaml = tmp_path / "config" / "channels.yaml"
    assert channels_yaml.exists()
    import yaml
    data = yaml.safe_load(channels_yaml.read_text())
    assert data["channels"]["web"]["enabled"] is True
    assert data["channels"]["web"]["port"] == 3000


def test_channel_add_web_default_port(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    result = runner.invoke(main, ["channel", "add", "web"])
    assert result.exit_code == 0
