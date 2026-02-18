"""CLI entry point for aifw."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from aifw.config import Config


def _load_config(project: str) -> Config:
    project_path = Path(project).resolve()
    config_path = project_path / "config.yaml"
    if not config_path.exists():
        config_path = project_path / ".aifw" / "config.yaml"
    config = Config.load(config_path if config_path.exists() else None)
    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)
    return config


@click.group()
@click.version_option()
def main():
    """aifw — AI Agent Framework for long-running development tasks."""
    pass


@main.command()
@click.option("--project", "-p", required=True, help="Path to the project directory")
@click.option("--goal", "-g", required=True, help="What to build")
def init(project: str, goal: str):
    """Initialize a project: analyze it and generate a feature plan."""
    from aifw.orchestrator import Orchestrator

    config = _load_config(project)
    orch = Orchestrator(project, config)
    orch.init(goal)


@main.command()
@click.option("--project", "-p", required=True, help="Path to the project directory")
@click.option("--feature", "-f", default=None, help="Specific feature ID to run")
def run(project: str, feature: str | None):
    """Run the development loop: implement features one by one."""
    from aifw.orchestrator import Orchestrator

    config = _load_config(project)
    orch = Orchestrator(project, config)
    orch.run(feature_id=feature)


@main.command()
@click.option("--project", "-p", required=True, help="Path to the project directory")
def status(project: str):
    """Show project progress and feature statuses."""
    from aifw.orchestrator import Orchestrator

    config = _load_config(project)
    orch = Orchestrator(project, config)
    orch.status()


@main.command()
@click.option("--project", "-p", required=True, help="Path to the project directory")
def next(project: str):
    """Show the next feature to be implemented."""
    from aifw.state.feature_store import FeatureStore

    state_dir = Path(project).resolve() / ".aifw"
    store = FeatureStore(state_dir / "features.json")

    if not store.exists():
        click.echo("No features.json found. Run 'aifw init' first.")
        return

    # Check for in-progress
    current = store.current_in_progress()
    if current:
        click.echo(f"In progress: [{current.priority}] {current.id}: {current.title}")
        for i, s in enumerate(current.steps):
            icon = "x" if s.done else " "
            click.echo(f"  [{icon}] {i}: {s.description}")
        return

    nxt = store.next_incomplete()
    if nxt is None:
        click.echo("All features completed!")
        return

    click.echo(f"Next: [{nxt.priority}] {nxt.id}: {nxt.title}")
    for i, s in enumerate(nxt.steps):
        click.echo(f"  [ ] {i}: {s.description}")
