# tests/test_dispatch.py
import json
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.subagent.dispatch import SubagentDispatcher, DispatchResult
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event


@pytest.fixture
def skill():
    return SkillManifest(
        name="test-skill",
        description="Test skill",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Test\nYou are a helpful test agent. Echo back what the user says.",
        tools=[],
        credentials=[],
    )


@pytest.fixture
def event():
    return Event(text="hello", channel="cli", user_id="local")


def _mock_run(stdout_result: str = "Echo: hello", stop_reason: str = "end_turn"):
    """Return a mock subprocess.CompletedProcess with JSON output."""
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = json.dumps({"result": stdout_result, "stop_reason": stop_reason})
    mock.stderr = ""
    return mock


def test_dispatch_returns_result_text(skill, event):
    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=_mock_run("Echo: hello")):
        result = dispatcher.dispatch(skill, event)

    assert isinstance(result, DispatchResult)
    assert result.text == "Echo: hello"
    assert result.skill_name == "test-skill"


def test_dispatch_uses_skill_body_as_system_prompt(skill, event):
    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=_mock_run()) as mock_run:
        dispatcher.dispatch(skill, event)

    cmd = mock_run.call_args.args[0]
    prompt_idx = cmd.index("--append-system-prompt")
    assert skill.body in cmd[prompt_idx + 1]


def test_dispatch_enforces_tool_permission(skill, event):
    """A skill with shell_policy=none should not add --allowedTools to the command."""
    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=_mock_run()) as mock_run:
        dispatcher.dispatch(skill, event)

    cmd = mock_run.call_args.args[0]
    assert "--allowedTools" not in cmd


def test_dispatch_injects_credentials_as_env_vars(skill, event, tmp_path, monkeypatch):
    """Credentials must appear in the subprocess env, not in the system prompt."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skill.credentials = ["erp-user"]

    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=_mock_run()) as mock_run:
        dispatcher.dispatch(skill, event, credentials={"erp-user": "alice"})

    call_kwargs = mock_run.call_args.kwargs
    env = call_kwargs.get("env", {})
    assert env.get("ERP_USER") == "alice"

    cmd = mock_run.call_args.args[0]
    prompt_idx = cmd.index("--append-system-prompt")
    system_prompt = cmd[prompt_idx + 1]
    assert "alice" not in system_prompt
