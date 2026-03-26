# tests/test_credential_injection.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.subagent.dispatch import SubagentDispatcher, credential_key_to_env_var
from claudeclaw.skills.loader import SkillManifest


def test_key_to_env_var_normalization():
    assert credential_key_to_env_var("erp-user") == "ERP_USER"
    assert credential_key_to_env_var("erp-password") == "ERP_PASSWORD"
    assert credential_key_to_env_var("email-token") == "EMAIL_TOKEN"
    assert credential_key_to_env_var("simple") == "SIMPLE"


def test_credentials_injected_as_env_vars_not_in_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    skill = SkillManifest(
        name="erp-skill",
        description="ERP task",
        trigger="on-demand",
        autonomy="autonomous",
        shell_policy="none",
        body="Do the ERP task.",
        credentials=["erp-user", "erp-password"],
    )
    credentials = {"erp-user": "alice", "erp-password": "s3cr3t"}

    dispatcher = SubagentDispatcher()
    mock_create = MagicMock(return_value=MagicMock(content=[MagicMock(text="done")], stop_reason="end_turn"))

    with patch.object(dispatcher._client.messages, "create", mock_create):
        dispatcher.dispatch(skill=skill, user_message="run", credentials=credentials)

    call_kwargs = mock_create.call_args.kwargs

    # Env vars must be present in the call
    env = call_kwargs.get("env") or {}
    assert env.get("ERP_USER") == "alice"
    assert env.get("ERP_PASSWORD") == "s3cr3t"

    # Secret values must NOT appear in the system prompt
    system_prompt = call_kwargs.get("system", "")
    assert "alice" not in system_prompt
    assert "s3cr3t" not in system_prompt


def test_missing_credential_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    skill = SkillManifest(
        name="needs-cred",
        description="needs a credential",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="",
        credentials=["missing-key"],
    )

    dispatcher = SubagentDispatcher()
    with pytest.raises(ValueError, match="missing-key"):
        dispatcher.dispatch(skill=skill, user_message="run", credentials={})
