import asyncio
import click
from claudeclaw.auth.oauth import AuthManager
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.core.router import Router
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.channels.cli_adapter import CliAdapter


@click.group()
def main():
    """ClaudeClaw — autonomous agent system powered by Claude."""
    pass


@main.command()
def login():
    """Authenticate with your Claude account."""
    auth = AuthManager()
    auth.login()


@main.command()
def logout():
    """Log out of your Claude account."""
    auth = AuthManager()
    auth.logout()


@main.command()
@click.option("--daemon", is_flag=True, help="Run as background daemon (not implemented in Plan 1)")
def start(daemon):
    """Start the ClaudeClaw orchestrator."""
    click.echo("Starting ClaudeClaw...")
    channel = CliAdapter()
    orchestrator = Orchestrator(channel=channel)
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        click.echo("\nStopped.")


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
        raise SystemExit(1)

    from claudeclaw.core.event import Event
    event = Event(text=message, channel="cli", user_id="local")
    dispatcher = SubagentDispatcher()

    click.echo(f"Running skill '{skill_name}'...")
    result = dispatcher.dispatch(skill, event)
    click.echo(result.text)
