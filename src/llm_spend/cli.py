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
from llm_spend.connectors import csv_import
from llm_spend.connectors import openai as openai_connector
from llm_spend.connectors.anthropic import AnthropicAdminAPIError
from llm_spend.connectors.csv_import import CSVImportError
from llm_spend.connectors.openai import OpenAIAdminAPIError
from llm_spend.report import render

app = typer.Typer(no_args_is_help=True)
console = Console()

CONNECTORS = {
    "openai": ("OPENAI_ADMIN_KEY", openai_connector.pull, openai_connector.fetch_reconciliation_total, OpenAIAdminAPIError),
    "anthropic": (
        "ANTHROPIC_ADMIN_KEY",
        anthropic_connector.pull,
        anthropic_connector.fetch_reconciliation_total,
        AnthropicAdminAPIError,
    ),
}


@app.command()
def pull(
    provider: Annotated[str, typer.Option(help="openai or anthropic")],
    since: Annotated[str, typer.Option(help="ISO date, e.g. 2026-06-01. Interpreted as UTC midnight.")],
    until: Annotated[
        str | None, typer.Option(help="ISO date, exclusive; defaults to now. Interpreted as UTC midnight.")
    ] = None,
) -> None:
    """Pull usage/cost data from a provider's admin API into the local cache."""
    if provider not in CONNECTORS:
        console.print(f"[red]unknown provider: {provider}[/red] (expected openai or anthropic)")
        raise typer.Exit(1)

    env_var, connector_pull, fetch_reconciliation_total, error_cls = CONNECTORS[provider]
    api_key = os.environ.get(env_var)
    if not api_key:
        console.print(f"[red]{env_var} is not set[/red]")
        raise typer.Exit(1)

    since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if until else None

    try:
        records = connector_pull(api_key, since=since_dt, until=until_dt)
        reconciliation_total = fetch_reconciliation_total(api_key, since=since_dt, until=until_dt)
    except error_cls as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    path = cache.write_records(provider, records)
    cache.write_reconciliation_total(provider, reconciliation_total, since_dt, until_dt)
    total_cost = sum(r.cost_usd for r in records)
    console.print(f"Pulled {len(records)} records (${total_cost:,.2f} total) -> {path}")


@app.command(name="import")
def import_csv(
    csv: Annotated[Path, typer.Option(help="Path to a usage export CSV")],
) -> None:
    """Import usage data from a CSV export instead of an admin API key."""
    if not csv.exists():
        console.print(f"[red]{csv} does not exist[/red]")
        raise typer.Exit(1)

    try:
        records = csv_import.parse_csv(csv)
    except CSVImportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not records:
        console.print(f"[yellow]No rows found in {csv}[/yellow]")
        raise typer.Exit(1)

    by_provider: dict[str, list] = {}
    for r in records:
        by_provider.setdefault(r.provider, []).append(r)

    for provider, provider_records in by_provider.items():
        path = cache.write_records(provider, provider_records)
        total_cost = sum(r.cost_usd for r in provider_records)
        console.print(f"Imported {len(provider_records)} {provider} records (${total_cost:,.2f} total) -> {path}")


@app.command()
def report(
    format: Annotated[str, typer.Option(help="terminal or html")] = "terminal",
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output path for --format html")] = None,
    share: Annotated[
        bool,
        typer.Option("--share", help="Anonymized: percentages/ratios instead of dollar amounts, masked key/project names"),
    ] = False,
) -> None:
    """Render a spend report from cached usage data."""
    records = cache.read_records("openai") + cache.read_records("anthropic")
    if not records:
        console.print("[red]No cached usage data found.[/red] Run `llm-spend pull` or `llm-spend import` first.")
        raise typer.Exit(1)

    reconciliation_totals = [
        t for t in (cache.read_reconciliation_total("openai"), cache.read_reconciliation_total("anthropic")) if t is not None
    ]
    provider_total = sum(reconciliation_totals) if reconciliation_totals else None

    data = render.build_report(records, provider_total=provider_total)

    if format == "terminal":
        render.render_terminal(data, console=console, share=share)
    elif format == "html":
        out_path = output or Path("report.html")
        out_path.write_text(render.render_html(data, share=share))
        console.print(f"Report written to {out_path}")
    else:
        console.print(f"[red]unknown format: {format}[/red] (expected terminal or html)")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
