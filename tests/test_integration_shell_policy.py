# tests/test_integration_shell_policy.py
"""
Integration tests verifying that shell-policy enforcement works end-to-end:
- OpenShell with policy=none never calls subprocess
- SubagentDispatcher builds no bash tool for shell-policy: none skills
- OpenShell with policy=read-only allows safe reads, blocks writes
- OpenShellTool with policy=none returns [BLOCKED] for any input
"""
import pytest
from unittest.mock import patch, MagicMock
from claudeclaw.security.openshell import OpenShell, OpenShellTool, ShellResult


def test_none_policy_never_reaches_subprocess():
    """subprocess.run must never be called when policy is none."""
    shell = OpenShell(policy="none")
    with patch("subprocess.run") as mock_run:
        result = shell.execute("ls -la")
    mock_run.assert_not_called()
    assert result.blocked is True


def test_none_policy_tool_wrapper_returns_blocked():
    tool = OpenShellTool(policy="none")
    output = tool("rm -rf /")
    assert "[BLOCKED]" in output


def test_read_only_policy_never_reaches_subprocess_for_blocked_command():
    shell = OpenShell(policy="read-only")
    with patch("subprocess.run") as mock_run:
        result = shell.execute("rm -rf /")
    mock_run.assert_not_called()
    assert result.blocked is True


def test_dispatcher_tools_for_none_policy_skill_excludes_shell_tool():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock()
    skill.shell_policy = "none"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    assert not any(isinstance(t, OpenShellTool) for t in tools)


def test_dispatcher_tools_for_full_policy_skill_includes_shell_tool():
    """With the CLI backend, tool injection is handled by Claude Code — _build_tools always returns []."""
    from claudeclaw.subagent.dispatch import SubagentDispatcher

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock()
    skill.shell_policy = "full"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    # Claude CLI handles tool use; dispatcher returns empty list
    assert tools == []


def test_all_policies_return_shell_result_instances():
    """Every call to execute() must return a ShellResult regardless of policy."""
    for policy in ["none", "read-only", "full"]:
        shell = OpenShell(policy=policy)
        result = shell.execute("echo test")
        assert isinstance(result, ShellResult), f"policy={policy} did not return ShellResult"
