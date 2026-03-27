# tests/test_channel_cli.py
import pytest
import yaml
from pathlib import Path
from click.testing import CliRunner
from claudeclaw.cli import main
from claudeclaw.config.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings before each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def runner():
    return CliRunner()


def test_channel_add_telegram_stores_token(runner, tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    mock_store = mocker.MagicMock()
    mocker.patch("claudeclaw.cli.CredentialStore", return_value=mock_store)

    result = runner.invoke(main, [
        "channel", "add", "telegram", "--token", "my-secret-token"
    ], catch_exceptions=False)

    assert result.exit_code == 0

    # Token written to credential store
    mock_store.set.assert_called_once_with("telegram-bot-token", "my-secret-token")

    # channels.yaml created
    channels_yaml = tmp_path / "config" / "channels.yaml"
    assert channels_yaml.exists()
    data = yaml.safe_load(channels_yaml.read_text())
    assert "telegram" in data["channels"]


def test_channel_add_telegram_idempotent(runner, tmp_path, monkeypatch, mocker):
    """Running channel add twice should not duplicate the entry."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    mock_store = mocker.MagicMock()
    mocker.patch("claudeclaw.cli.CredentialStore", return_value=mock_store)

    runner.invoke(main, ["channel", "add", "telegram", "--token", "tok1"], catch_exceptions=False)
    runner.invoke(main, ["channel", "add", "telegram", "--token", "tok2"], catch_exceptions=False)

    channels_yaml = tmp_path / "config" / "channels.yaml"
    data = yaml.safe_load(channels_yaml.read_text())
    assert "telegram" in data["channels"]
    assert data["channels"]["telegram"]["enabled"] is True


def test_channel_add_requires_token(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    result = runner.invoke(main, ["channel", "add", "telegram"])
    assert result.exit_code != 0
