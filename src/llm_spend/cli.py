"""llm-spend: read-only CLI for LLM API spend attribution and reporting."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from llm_spend import cache
from llm_spend.connectors import anthropic as anthropic_connector
from llm_spend.connectors import openai as openai_connector
from llm_spend.connectors.anthropic import AnthropicAdminAPIError
from llm_spend.connectors.openai import OpenAIAdminAPIError

app = typer.Typer(no_args_is_help=True)
console = Console()

CONNECTORS = {
    "openai": ("OPENAI_ADMIN_KEY", openai_connector.pull, OpenAIAdminAPIError),
    "anthropic": ("ANTHROPIC_ADMIN_KEY", anthropic_connector.pull, AnthropicAdminAPIError),
}


@app.command()
def pull(
    provider: Annotated[str, typer.Option(help="openai or anthropic")],
    since: Annotated[str, typer.Option(help="ISO date, e.g. 2026-06-01")],
) -> None:
    """Pull usage/cost data from a provider's admin API into the local cache."""
    if provider not in CONNECTORS:
        console.print(f"[red]unknown provider: {provider}[/red] (expected openai or anthropic)")
        raise typer.Exit(1)

    env_var, connector_pull, error_cls = CONNECTORS[provider]
    api_key = os.environ.get(env_var)
    if not api_key:
        console.print(f"[red]{env_var} is not set[/red]")
        raise typer.Exit(1)

    since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)

    try:
        records = connector_pull(api_key, since=since_dt)
    except error_cls as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    path = cache.write_records(provider, records)
    total_cost = sum(r.cost_usd for r in records)
    console.print(f"Pulled {len(records)} records (${total_cost:,.2f} total) -> {path}")


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
