"""Report rendering: terminal (rich) and a single self-contained HTML file.

This module has no analysis logic of its own — it assembles what
analysis/* computes into one ReportData bundle, then formats it two ways.
All the language hedging (forecast disclaimer, batch heuristic, anomaly
confidence tiers) lives here since it's a presentation concern, not a math
one; the analysis modules only ever return numbers.

Both render functions take a `share` flag: the anonymized mode meant for
posting a screenshot publicly (Slack, HN, etc.) without leaking real
spend. Sections with no safe percentage/ratio substitute for an absolute
dollar figure (total spend, forecast, overspend scenario, reconciliation)
are dropped entirely rather than forced into a misleading percentage; the
rest either already report a rate/percentage (cache hit rate) or get one
computed here (batch savings %, anomaly cost expressed as a multiple of
typical). API key and project names are replaced with generic labels
("key-1", "project-1", ...) consistent within one render call — model
names stay visible since they're not private identifiers.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from llm_spend.analysis import attribution, forecast, risk, whatif
from llm_spend.pricing import load_pricing
from llm_spend.schema import UsageRecord

RECONCILIATION_DIVERGENCE_THRESHOLD = 0.01  # 1%


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    our_total: float
    provider_total: float | None
    divergence_pct: float | None
    flagged: bool
    note: str


@dataclass(frozen=True, slots=True)
class ReportData:
    total_cost: float
    by_model: list[attribution.BreakdownRow]
    by_api_key: list[attribution.BreakdownRow]
    by_project: list[attribution.BreakdownRow]
    most_expensive_day: tuple | None
    top_movers_by_model: list[attribution.MoverRow]
    forecast: forecast.ForecastResult | None
    overspend: risk.OverspendScenario | None
    anomalies: risk.AnomalyResult
    batch_gap: list[whatif.BatchGapRow]
    service_tier_gap: dict[str, list[whatif.TierRow]]
    cache_hit_rate: list[whatif.CacheHitRow]
    reconciliation: ReconciliationResult


def _build_reconciliation(our_total: float, provider_total: float | None) -> ReconciliationResult:
    divergence_pct = None
    flagged = False
    if provider_total is not None and provider_total > 0:
        divergence_pct = abs(our_total - provider_total) / provider_total
        flagged = divergence_pct > RECONCILIATION_DIVERGENCE_THRESHOLD

    if provider_total is None:
        note = "All bucket timestamps are UTC. Cross-check this total against your provider's billing dashboard."
    elif flagged:
        note = "All bucket timestamps are UTC. This diverges from the provider's total by more than 1% — investigate before trusting this report."
    else:
        note = "All bucket timestamps are UTC. Matches the provider's reported total within 1%."

    return ReconciliationResult(
        our_total=our_total, provider_total=provider_total, divergence_pct=divergence_pct, flagged=flagged, note=note
    )


def build_report(records: list[UsageRecord], provider_total: float | None = None) -> ReportData:
    pricing = load_pricing()
    total = attribution.total_cost(records)
    return ReportData(
        total_cost=total,
        by_model=attribution.breakdown(records, "model"),
        by_api_key=attribution.breakdown(records, "api_key_id"),
        by_project=attribution.breakdown(records, "project"),
        most_expensive_day=attribution.most_expensive_day(records),
        top_movers_by_model=attribution.top_movers(records, "model"),
        forecast=forecast.forecast_month_end(records),
        overspend=risk.overspend_scenario(records),
        anomalies=risk.detect_anomalies(records),
        batch_gap=whatif.batch_gap(records, pricing),
        service_tier_gap=whatif.service_tier_gap(records),
        cache_hit_rate=whatif.cache_hit_rate(records),
        reconciliation=_build_reconciliation(total, provider_total),
    )


def _mask_labels(rows: list[attribution.BreakdownRow], prefix: str) -> dict[str, str]:
    """Consistent generic labels for one render call — "(none)" (the
    breakdown's own placeholder for a missing key/project) stays as-is
    since it isn't a real identifier to begin with."""
    mapping = {}
    counter = 1
    for row in rows:
        if row.value == "(none)":
            mapping[row.value] = row.value
            continue
        mapping[row.value] = f"{prefix}-{counter}"
        counter += 1
    return mapping


def _anomaly_ratio_label(a: risk.Anomaly) -> str:
    if a.reference_mean <= 0:
        return "n/a"
    return f"{a.cost_usd / a.reference_mean:.1f}x typical"


def _breakdown_table(title: str, rows: list[attribution.BreakdownRow], share: bool, mask: dict[str, str] | None = None) -> Table:
    table = Table(title=title)
    table.add_column(title.split(" ")[-1].strip("()").lower() or "value")
    if not share:
        table.add_column("cost", justify="right")
    table.add_column("share", justify="right")
    for row in rows[:10]:
        label = mask.get(row.value, row.value) if mask else row.value
        if share:
            table.add_row(label, f"{row.share:.0%}")
        else:
            table.add_row(label, f"${row.cost_usd:,.2f}", f"{row.share:.0%}")
    return table


def render_terminal(data: ReportData, console: Console | None = None, share: bool = False) -> None:
    console = console or Console()

    if share:
        console.print(Panel("[bold]llm-spend report[/bold] (shared — dollar totals hidden)", title="llm-spend report"))
    else:
        console.print(Panel(f"[bold]Total spend:[/bold] ${data.total_cost:,.2f}", title="llm-spend report"))
        console.print(f"[dim]{data.reconciliation.note}[/dim]")
        if data.reconciliation.flagged:
            console.print(f"[bold red]Reconciliation flagged: {data.reconciliation.divergence_pct:.1%} divergence[/bold red]")

    if data.most_expensive_day:
        day, cost = data.most_expensive_day
        if share:
            console.print(f"\n[bold]Most expensive day:[/bold] {day.isoformat()}")
        else:
            console.print(f"\n[bold]Most expensive day:[/bold] {day.isoformat()} (${cost:,.2f})")

    key_mask = _mask_labels(data.by_api_key, "key") if share else None
    project_mask = _mask_labels(data.by_project, "project") if share else None

    console.print(_breakdown_table("By model", data.by_model, share))
    console.print(_breakdown_table("By API key", data.by_api_key, share, key_mask))
    console.print(_breakdown_table("By project", data.by_project, share, project_mask))

    if data.top_movers_by_model:
        table = Table(title="Top movers by model (last 7 days vs previous 7)")
        table.add_column("model")
        if not share:
            table.add_column("recent", justify="right")
            table.add_column("previous", justify="right")
        table.add_column("change", justify="right")
        for row in data.top_movers_by_model[:5]:
            change = "new" if row.pct_change is None else f"{row.pct_change:+.0%}"
            if share:
                table.add_row(row.value, change)
            else:
                table.add_row(row.value, f"${row.recent_cost:,.2f}", f"${row.previous_cost:,.2f}", change)
        console.print(table)

    if not share and data.forecast:
        f = data.forecast
        console.print(
            f"\n[bold]Forecast:[/bold] ${f.projected_total:,.2f} by end of month "
            f"(day {f.days_elapsed}/{f.days_in_month}, ${f.daily_average:,.2f}/day average)"
        )
        console.print(f"[dim]{f.disclaimer}[/dim]")

    if not share and data.overspend:
        console.print(f"\n[bold]Overspend scenario:[/bold] ${data.overspend.worst_case_projection:,.2f}/month if your worst day repeated every day")
        console.print(f"[dim]{data.overspend.note}[/dim]")

    if data.anomalies.insufficient_history:
        console.print(f"\n[bold]Anomalies:[/bold] [dim]{data.anomalies.note}[/dim]")
    elif data.anomalies.anomalies:
        table = Table(title="Anomalies (vs. same weekday's history)")
        table.add_column("day")
        table.add_column("cost" if not share else "vs. typical", justify="right")
        table.add_column("z-score", justify="right")
        table.add_column("confidence")
        for a in data.anomalies.anomalies:
            z = "inf" if a.z_score == float("inf") else f"{a.z_score:.1f}"
            cost_col = _anomaly_ratio_label(a) if share else f"${a.cost_usd:,.2f}"
            table.add_row(a.day.isoformat(), cost_col, z, a.confidence)
        console.print(table)
    else:
        console.print("\n[bold]Anomalies:[/bold] none found")

    if data.batch_gap:
        table = Table(title="Potential batch savings (heuristic — only if the workload doesn't need to be real-time)")
        table.add_column("model")
        if share:
            table.add_column("potential savings", justify="right")
        else:
            table.add_column("actual cost", justify="right")
            table.add_column("potential batch cost", justify="right")
            table.add_column("potential savings", justify="right")
        for row in data.batch_gap[:5]:
            if share:
                pct = (row.potential_savings / row.actual_cost) if row.actual_cost else 0.0
                table.add_row(row.model, f"{pct:.0%}")
            else:
                table.add_row(
                    row.model, f"${row.actual_cost:,.2f}", f"${row.hypothetical_batch_cost:,.2f}", f"${row.potential_savings:,.2f}"
                )
        console.print(table)
        console.print(f"[dim]{whatif.BATCH_GAP_CACHE_CAVEAT}[/dim]")

    if data.service_tier_gap:
        for model, tiers in list(data.service_tier_gap.items())[:5]:
            table = Table(title=f"Service tier cost per 1K tokens — {model}")
            table.add_column("tier")
            if share:
                cheapest = min(row.cost_per_1k_tokens for row in tiers) or 1.0
                table.add_column("relative cost", justify="right")
            else:
                table.add_column("cost/1K tokens", justify="right")
            table.add_column("output token share", justify="right")
            for row in tiers:
                if share:
                    table.add_row(row.service_tier, f"{row.cost_per_1k_tokens / cheapest:.0%}", f"{row.output_token_share:.0%}")
                else:
                    table.add_row(row.service_tier, f"${row.cost_per_1k_tokens:.3f}", f"{row.output_token_share:.0%}")
            console.print(table)
        console.print(f"[dim]{whatif.SERVICE_TIER_GAP_CAVEAT}[/dim]")

    if data.cache_hit_rate:
        table = Table(title="Cache hit rate by model")
        table.add_column("model")
        table.add_column("hit rate", justify="right")
        for row in data.cache_hit_rate[:10]:
            table.add_row(row.model, f"{row.hit_rate:.0%}")
        console.print(table)


def _html_breakdown_table(title: str, rows: list[attribution.BreakdownRow], share: bool, mask: dict[str, str] | None = None) -> str:
    if share:
        body = "".join(
            f"<tr><td>{html.escape(mask.get(row.value, row.value) if mask else row.value)}</td><td>{row.share:.0%}</td></tr>"
            for row in rows[:10]
        )
        return f"<h3>{html.escape(title)}</h3><table><tr><th>value</th><th>share</th></tr>{body}</table>"
    body = "".join(
        f"<tr><td>{html.escape(row.value)}</td><td>${row.cost_usd:,.2f}</td><td>{row.share:.0%}</td></tr>" for row in rows[:10]
    )
    return f"<h3>{html.escape(title)}</h3><table><tr><th>value</th><th>cost</th><th>share</th></tr>{body}</table>"


def render_html(data: ReportData, share: bool = False) -> str:
    key_mask = _mask_labels(data.by_api_key, "key") if share else None
    project_mask = _mask_labels(data.by_project, "project") if share else None

    sections = [_html_breakdown_table("By model", data.by_model, share)]
    sections.append(_html_breakdown_table("By API key", data.by_api_key, share, key_mask))
    sections.append(_html_breakdown_table("By project", data.by_project, share, project_mask))

    if data.most_expensive_day:
        day, cost = data.most_expensive_day
        if share:
            sections.append(f"<p><strong>Most expensive day:</strong> {day.isoformat()}</p>")
        else:
            sections.append(f"<p><strong>Most expensive day:</strong> {day.isoformat()} (${cost:,.2f})</p>")

    if not share and data.forecast:
        f = data.forecast
        sections.append(
            f"<h3>Forecast</h3><p>${f.projected_total:,.2f} by end of month "
            f"(day {f.days_elapsed}/{f.days_in_month}, ${f.daily_average:,.2f}/day average)</p>"
            f"<p class='disclaimer'>{html.escape(f.disclaimer)}</p>"
        )

    if not share and data.overspend:
        sections.append(
            f"<h3>Overspend scenario</h3><p>${data.overspend.worst_case_projection:,.2f}/month if your worst day "
            f"repeated every day</p><p class='disclaimer'>{html.escape(data.overspend.note)}</p>"
        )

    if data.anomalies.insufficient_history:
        sections.append(f"<h3>Anomalies</h3><p class='disclaimer'>{html.escape(data.anomalies.note)}</p>")
    elif data.anomalies.anomalies:
        cost_header = "vs. typical" if share else "cost"
        rows = "".join(
            f"<tr><td>{a.day.isoformat()}</td><td>{_anomaly_ratio_label(a) if share else f'${a.cost_usd:,.2f}'}</td>"
            f"<td>{'inf' if a.z_score == float('inf') else f'{a.z_score:.1f}'}</td><td>{html.escape(a.confidence)}</td></tr>"
            for a in data.anomalies.anomalies
        )
        sections.append(
            "<h3>Anomalies (vs. same weekday's history)</h3>"
            f"<table><tr><th>day</th><th>{cost_header}</th><th>z-score</th><th>confidence</th></tr>{rows}</table>"
        )
    else:
        sections.append("<h3>Anomalies</h3><p>None found.</p>")

    if data.batch_gap:
        if share:
            rows = "".join(
                f"<tr><td>{html.escape(row.model)}</td>"
                f"<td>{(row.potential_savings / row.actual_cost) if row.actual_cost else 0.0:.0%}</td></tr>"
                for row in data.batch_gap[:5]
            )
            header = "<tr><th>model</th><th>potential savings</th></tr>"
        else:
            rows = "".join(
                f"<tr><td>{html.escape(row.model)}</td><td>${row.actual_cost:,.2f}</td>"
                f"<td>${row.hypothetical_batch_cost:,.2f}</td><td>${row.potential_savings:,.2f}</td></tr>"
                for row in data.batch_gap[:5]
            )
            header = "<tr><th>model</th><th>actual cost</th><th>potential batch cost</th><th>potential savings</th></tr>"
        sections.append(
            "<h3>Potential batch savings</h3>"
            "<p class='disclaimer'>Heuristic — only if the workload doesn't need to be real-time.</p>"
            f"<p class='disclaimer'>{html.escape(whatif.BATCH_GAP_CACHE_CAVEAT)}</p>"
            f"<table>{header}{rows}</table>"
        )

    if data.service_tier_gap:
        tier_sections = []
        for model, tiers in list(data.service_tier_gap.items())[:5]:
            if share:
                cheapest = min(row.cost_per_1k_tokens for row in tiers) or 1.0
                rows = "".join(
                    f"<tr><td>{html.escape(row.service_tier)}</td><td>{row.cost_per_1k_tokens / cheapest:.0%}</td>"
                    f"<td>{row.output_token_share:.0%}</td></tr>"
                    for row in tiers
                )
                header = "<tr><th>tier</th><th>relative cost</th><th>output token share</th></tr>"
            else:
                rows = "".join(
                    f"<tr><td>{html.escape(row.service_tier)}</td><td>${row.cost_per_1k_tokens:.3f}</td>"
                    f"<td>{row.output_token_share:.0%}</td></tr>"
                    for row in tiers
                )
                header = "<tr><th>tier</th><th>cost/1K tokens</th><th>output token share</th></tr>"
            tier_sections.append(f"<h4>{html.escape(model)}</h4><table>{header}{rows}</table>")
        sections.append(
            "<h3>Service tier cost per 1K tokens</h3>"
            f"<p class='disclaimer'>{html.escape(whatif.SERVICE_TIER_GAP_CAVEAT)}</p>" + "".join(tier_sections)
        )

    if data.cache_hit_rate:
        rows = "".join(f"<tr><td>{html.escape(row.model)}</td><td>{row.hit_rate:.0%}</td></tr>" for row in data.cache_hit_rate[:10])
        sections.append(f"<h3>Cache hit rate by model</h3><table><tr><th>model</th><th>hit rate</th></tr>{rows}</table>")

    body = "\n".join(sections)

    if share:
        header_html = '<p class="total">llm-spend report</p><p class="reconciliation">Shared report — dollar totals hidden.</p>'
    else:
        reconciliation_class = "flagged" if data.reconciliation.flagged else ""
        header_html = (
            f'<p class="total">${data.total_cost:,.2f}</p>'
            f'<p class="reconciliation {reconciliation_class}">{html.escape(data.reconciliation.note)}</p>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>llm-spend report</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.5rem; }}
  h3 {{ margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; }}
  .disclaimer {{ color: #666; font-size: 0.9rem; font-style: italic; }}
  .total {{ font-size: 1.75rem; font-weight: bold; }}
  .reconciliation {{ color: #666; font-size: 0.9rem; }}
  .reconciliation.flagged {{ color: #b00020; font-weight: bold; }}
</style>
</head>
<body>
<h1>llm-spend report</h1>
{header_html}
{body}
</body>
</html>
"""
