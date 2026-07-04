"""llm-spend: read-only CLI for LLM API spend attribution and reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def pull(
    provider: Annotated[str, typer.Option(help="openai or anthropic")],
    since: Annotated[str, typer.Option(help="ISO date, e.g. 2026-06-01")],
) -> None:
    """Pull usage/cost data from a provider's admin API into the local cache."""
    raise NotImplementedError(f"pull for {provider} since {since} not yet implemented")


@app.command(name="import")
def import_csv(
    csv: Annotated[Path, typer.Option(help="Path to a usage export CSV")],
) -> None:
    """Import usage data from a CSV export instead of an admin API key."""
    raise NotImplementedError(f"import from {csv} not yet implemented")


@app.command()
def report(
    format: Annotated[str, typer.Option(help="terminal or html")] = "terminal",
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output path for --format html")] = None,
) -> None:
    """Render a spend report from cached usage data."""
    raise NotImplementedError(f"report --format {format} output={output} not yet implemented")


if __name__ == "__main__":
    app()
