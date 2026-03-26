import asyncio
import sys
import yaml as _yaml
import click
from claudeclaw.auth.oauth import AuthManager
from claudeclaw.auth.keyring import CredentialStore
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.channels.cli_adapter import CliAdapter
from claudeclaw.core.event import Event


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
