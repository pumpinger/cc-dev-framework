"""CLI entry point for aifw."""

import click


@click.group()
@click.version_option()
def main():
    """aifw — AI Agent Framework for long-running development tasks."""
    pass
