import pytest
from pathlib import Path
from claudeclaw.mcps.config import MCPConfig, load_mcps, save_mcps, add_mcp, remove_mcp, resolve_mcps
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_load_empty_returns_empty_list(mcp_env):
    assert load_mcps() == []


def test_add_and_load_mcp(mcp_env):
    cfg = MCPConfig(name="filesystem", command="npx", args=["-y", "@mcp/fs"], scope="global")
    add_mcp(cfg)
    mcps = load_mcps()
    assert len(mcps) == 1
    assert mcps[0].name == "filesystem"
    assert mcps[0].scope == "global"


def test_add_duplicate_raises(mcp_env):
    cfg = MCPConfig(name="filesystem", command="npx", args=[], scope="global")
    add_mcp(cfg)
    with pytest.raises(ValueError, match="already exists"):
        add_mcp(cfg)


def test_remove_mcp(mcp_env):
    add_mcp(MCPConfig(name="postgres", command="npx", args=[], scope="agent"))
    remove_mcp("postgres")
    assert load_mcps() == []


def test_remove_nonexistent_raises(mcp_env):
    with pytest.raises(KeyError):
        remove_mcp("does-not-exist")


def test_resolve_mcps_global_always_included(mcp_env):
    add_mcp(MCPConfig(name="filesystem", command="npx", args=[], scope="global"))
    skill = SkillManifest(name="test", description="t", trigger="on-demand",
                          autonomy="ask", shell_policy="none", body="")
    result = resolve_mcps(skill)
    assert any(m.name == "filesystem" for m in result)


def test_resolve_mcps_agent_only_when_declared(mcp_env):
    add_mcp(MCPConfig(name="postgres", command="npx", args=[], scope="agent"))
    skill_without = SkillManifest(name="test", description="t", trigger="on-demand",
                                  autonomy="ask", shell_policy="none", body="")
    skill_with = SkillManifest(name="test", description="t", trigger="on-demand",
                               autonomy="ask", shell_policy="none", body="", mcps_agent=["postgres"])
    assert not any(m.name == "postgres" for m in resolve_mcps(skill_without))
    assert any(m.name == "postgres" for m in resolve_mcps(skill_with))


def test_resolve_mcps_via_mcps_field(mcp_env):
    add_mcp(MCPConfig(name="gmail", command="npx", args=[], scope="agent"))
    skill = SkillManifest(name="test", description="t", trigger="on-demand",
                          autonomy="ask", shell_policy="none", body="", mcps=["gmail"])
    assert any(m.name == "gmail" for m in resolve_mcps(skill))
