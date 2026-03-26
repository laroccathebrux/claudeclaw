# tests/test_dispatch_openshell.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.security.openshell import OpenShellTool, ShellResult


def test_openshell_tool_returns_stdout_on_success():
    tool = OpenShellTool(policy="full")
    with patch.object(tool._shell, "execute") as mock_exec:
        mock_exec.return_value = ShellResult(
            stdout="hello\n", stderr="", exit_code=0, blocked=False
        )
        result = tool("echo hello")
    assert result == "hello\n"


def test_openshell_tool_returns_blocked_message_when_blocked():
    tool = OpenShellTool(policy="none")
    result = tool("ls -la")
    assert "[BLOCKED]" in result


def test_openshell_tool_returns_exit_code_on_failure():
    tool = OpenShellTool(policy="full")
    with patch.object(tool._shell, "execute") as mock_exec:
        mock_exec.return_value = ShellResult(
            stdout="", stderr="No such file", exit_code=2, blocked=False
        )
        result = tool("cat /nonexistent")
    assert "[EXIT 2]" in result
    assert "No such file" in result


def test_dispatcher_builds_no_bash_tool_for_none_policy():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.skills.loader import SkillManifest

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock(spec=SkillManifest)
    skill.shell_policy = "none"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    tool_types = [type(t).__name__ for t in tools]
    assert "OpenShellTool" not in tool_types


def test_dispatcher_injects_openshell_tool_for_read_only_policy():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.skills.loader import SkillManifest
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock(spec=SkillManifest)
    skill.shell_policy = "read-only"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    shell_tools = [t for t in tools if isinstance(t, OpenShellTool)]
    assert len(shell_tools) == 1
    assert shell_tools[0]._shell._policy == "read-only"


def test_dispatcher_injects_openshell_tool_for_restricted_policy():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock()
    skill.shell_policy = "restricted"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    shell_tools = [t for t in tools if isinstance(t, OpenShellTool)]
    assert len(shell_tools) == 1
    assert shell_tools[0]._shell._policy == "restricted"
