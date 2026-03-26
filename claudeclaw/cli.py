import asyncio
import sys
import yaml as _yaml
import click
from claudeclaw.auth.oauth import AuthManager
from claudeclaw.auth.keyring import CredentialStore
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher, dispatch_skill
from claudeclaw.config.settings import get_settings as _get_settings
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.channels.cli_adapter import CliAdapter
from claudeclaw.core.event import Event
from claudeclaw.mcps.config import MCPConfig, load_mcps, add_mcp, remove_mcp
from claudeclaw.plugins.manager import (
    install as plugin_install_manager,
    list_plugins,
    uninstall as plugin_uninstall_manager,
)


@click.group()
def main():
    """ClaudeClaw — autonomous agent system powered by Claude."""
    pass


@main.command()
def login():
    """Authenticate with your Claude account."""
    try:
        auth = AuthManager()
        auth.login()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
def logout():
    """Log out of your Claude account."""
    try:
        auth = AuthManager()
        auth.logout()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--daemon", is_flag=True, help="Run as background daemon (not implemented in Plan 1)")
def start(daemon):
    """Start the ClaudeClaw orchestrator."""
    click.echo("Starting ClaudeClaw...")

    async def _run():
        channel = CliAdapter()
        registry = SkillRegistry()
        from claudeclaw.auth.keyring import CredentialStore
        credential_store = CredentialStore()
        orchestrator = Orchestrator(skill_registry=registry, credential_store=credential_store)
        queue = asyncio.Queue()

        async def _feed_queue():
            async for event in channel.receive():
                event.channel_adapter = channel
                await queue.put(event)

        await asyncio.gather(_feed_queue(), orchestrator.run(queue))

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    except Exception as e:
        click.echo(f"Orchestrator error: {e}", err=True)
        sys.exit(1)


@main.group()
def skills():
    """Manage skills."""
    pass


@skills.command("list")
def skills_list():
    """List all installed skills."""
    registry = SkillRegistry()
    all_skills = registry.list_skills()
    if not all_skills:
        click.echo("No skills installed. Install from marketplace: claudeclaw install <skill>")
        return
    for skill in all_skills:
        trigger_info = f"[{skill.trigger}]"
        if skill.schedule:
            trigger_info = f"[cron: {skill.schedule}]"
        click.echo(f"  {skill.name:<30} {trigger_info:<25} {skill.description}")


@main.group()
def agents():
    """Manage agents."""
    pass


@agents.command("run")
@click.argument("skill_name")
@click.argument("message", default="run")
def agents_run(skill_name, message):
    """Manually trigger a skill by name."""
    registry = SkillRegistry()
    skill = registry.find(skill_name)
    if skill is None:
        click.echo(f"Skill '{skill_name}' not found. Run 'claudeclaw skills list' to see available skills.")
        sys.exit(1)

    event = Event(text=message, channel="cli", user_id="local")
    dispatcher = SubagentDispatcher()

    click.echo(f"Running skill '{skill_name}'...")
    try:
        result = dispatcher.dispatch(skill, event)
    except Exception as e:
        click.echo(f"Error running '{skill_name}': {e}", err=True)
        sys.exit(1)
    click.echo(result.text)


@main.group()
def channel():
    """Manage channel adapters (Telegram, Slack, etc.)."""


@channel.command("add")
@click.argument("channel_type")
@click.option("--token", required=True, help="Bot or API token for the channel.")
def channel_add(channel_type: str, token: str):
    """Add and configure a channel adapter."""
    from claudeclaw.config.settings import get_settings

    try:
        settings = get_settings()
        store = CredentialStore()

        # Store token in credential store
        token_key = f"{channel_type}-bot-token"
        store.set(token_key, token)

        # Upsert entry in channels.yaml
        channels_file = settings.config_dir / "channels.yaml"
        if channels_file.exists():
            data = _yaml.safe_load(channels_file.read_text()) or {}
        else:
            data = {}

        channels = data.get("channels", [])
        # Remove existing entry for this channel type (idempotent)
        channels = [c for c in channels if c.get("type") != channel_type]
        channels.append({"type": channel_type, "enabled": True})
        data["channels"] = channels
        channels_file.write_text(_yaml.dump(data, default_flow_style=False))

        click.echo(f"Channel '{channel_type}' configured. Token stored securely.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.group()
def schedule():
    """Manage scheduled skills (cron and webhook triggers)."""


@schedule.command("list")
def schedule_list():
    """List all registered cron schedules and webhook triggers."""
    settings = _get_settings()

    schedules_file = settings.config_dir / "schedules.yaml"
    triggers_file = settings.config_dir / "triggers.yaml"

    schedules = {}
    if schedules_file.exists():
        schedules = _yaml.safe_load(schedules_file.read_text()) or {}

    triggers = {}
    if triggers_file.exists():
        triggers = _yaml.safe_load(triggers_file.read_text()) or {}

    if not schedules and not triggers:
        click.echo("No schedules or webhook triggers registered.")
        return

    if schedules:
        click.echo("\nCRON SCHEDULES")
        for skill_name, meta in schedules.items():
            click.echo(f"  {skill_name:<25} {meta.get('schedule', '?'):<20} {meta.get('cron_id', '?')}")

    if triggers:
        click.echo("\nWEBHOOK TRIGGERS")
        for trigger_id, meta in triggers.items():
            click.echo(
                f"  {trigger_id:<25} skill: {meta['skill_name']:<20} {meta['webhook_url']}"
            )


@schedule.command("run")
@click.argument("skill_name")
def schedule_run(skill_name: str):
    """Manually fire a scheduled skill immediately."""
    settings = _get_settings()
    registry = SkillRegistry(skills_dir=settings.skills_dir)
    skill = registry.find(skill_name)

    if skill is None:
        click.echo(f"Error: skill '{skill_name}' not found.", err=True)
        raise SystemExit(1)

    click.echo(f"Firing {skill_name} manually...")

    event = Event(
        text="",
        channel="manual",
        source="manual",
        skill_name=skill_name,
        payload={},
        channel_reply_fn=None,
    )

    async def _run():
        return await dispatch_skill(skill=skill, event=event)

    result = asyncio.run(_run())
    click.echo(f"Done. Result: {result}")


@main.group()
def mcp():
    """Manage MCP server configurations."""
    pass


@mcp.command("add")
@click.argument("name")
@click.option("--command", required=True, help="Executable to launch the MCP server")
@click.option("--args", multiple=True, help="Arguments for the MCP server command")
@click.option("--env", "env_vars", multiple=True, help="Environment variables as KEY=VALUE pairs")
@click.option("--scope", type=click.Choice(["global", "agent"]), default="agent",
              show_default=True, help="global = all subagents; agent = per-skill opt-in")
def mcp_add(name, command, args, env_vars, scope):
    """Register a new MCP server configuration."""
    env_dict = {}
    for item in env_vars:
        if "=" not in item:
            raise click.BadParameter(f"env must be KEY=VALUE, got: {item}")
        k, v = item.split("=", 1)
        env_dict[k] = v
    try:
        add_mcp(MCPConfig(name=name, command=command, args=list(args), env=env_dict, scope=scope))
        click.echo(f"MCP '{name}' registered (scope: {scope}).")
    except ValueError as e:
        raise click.ClickException(str(e))


@mcp.command("list")
def mcp_list():
    """List all configured MCP servers."""
    mcps = load_mcps()
    if not mcps:
        click.echo("No MCPs configured. Use 'claudeclaw mcp add' to register one.")
        return
    click.echo(f"{'NAME':<20} {'SCOPE':<10} {'COMMAND'}")
    click.echo("-" * 50)
    for m in mcps:
        click.echo(f"{m.name:<20} {m.scope:<10} {m.command} {' '.join(m.args)}")


@main.group()
def plugin():
    """Manage ClaudeClaw plugins."""
    pass


@plugin.command("install")
@click.argument("name")
def plugin_install(name):
    """Install a plugin from PyPI (claudeclaw-plugin-<name>)."""
    try:
        plugin_install_manager(name)
    except RuntimeError as e:
        raise click.ClickException(str(e))


@plugin.command("list")
def plugin_list():
    """List installed plugins."""
    records = list_plugins()
    if not records:
        click.echo("No plugins installed. Use 'claudeclaw plugin install <name>'.")
        return
    click.echo(f"{'NAME':<20} {'VERSION':<10} {'MCPS':<6} {'SKILLS':<8} {'INSTALLED'}")
    click.echo("-" * 65)
    for r in records:
        click.echo(f"{r.name:<20} {r.version:<10} {len(r.mcps):<6} {len(r.skills):<8} {r.installed_at[:10]}")


@plugin.command("uninstall")
@click.argument("name")
def plugin_uninstall(name):
    """Uninstall a plugin and remove its MCPs and skills."""
    try:
        plugin_uninstall_manager(name)
    except KeyError as e:
        raise click.ClickException(str(e))


@mcp.command("remove")
@click.argument("name")
def mcp_remove(name):
    """Remove a registered MCP server."""
    try:
        remove_mcp(name)
        click.echo(f"MCP '{name}' removed.")
    except KeyError as e:
        raise click.ClickException(str(e))
