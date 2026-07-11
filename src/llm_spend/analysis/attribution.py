"""Cost attribution: breakdowns by key/model/project, and top movers over a period."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from llm_spend.analysis._timeseries import daily_totals
from llm_spend.schema import UsageRecord

Dimension = Literal["api_key_id", "model", "project"]


@dataclass(frozen=True, slots=True)
class BreakdownRow:
    value: str
    cost_usd: Decimal
    share: float  # of total cost across all rows, 0..1 — a ratio, not a dollar amount


@dataclass(frozen=True, slots=True)
class MoverRow:
    value: str
    recent_cost: Decimal
    previous_cost: Decimal
    delta: Decimal
    pct_change: float | None  # None when previous_cost == 0 (no baseline to divide by)


def total_cost(records: list[UsageRecord]) -> Decimal:
    return sum((r.cost_usd for r in records), start=Decimal(0))


def breakdown(records: list[UsageRecord], dimension: Dimension) -> list[BreakdownRow]:
    """Cost grouped by `dimension`, sorted highest cost first."""
    totals: dict[str, Decimal] = {}
    for r in records:
        value = getattr(r, dimension) or "(none)"
        totals[value] = totals.get(value, Decimal(0)) + r.cost_usd
    grand_total = sum(totals.values(), start=Decimal(0)) or Decimal(1)
    rows = [BreakdownRow(value=v, cost_usd=c, share=float(c / grand_total)) for v, c in totals.items()]
    rows.sort(key=lambda row: row.cost_usd, reverse=True)
    return rows


def most_expensive_day(records: list[UsageRecord]) -> tuple[date, Decimal] | None:
    totals = daily_totals(records)
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])


def top_movers(records: list[UsageRecord], dimension: Dimension, recent_days: int = 7) -> list[MoverRow]:
    """Compare the most recent `recent_days` of cost against the
    equal-length window immediately before it, broken down by `dimension`.
    Sorted by |delta| descending."""
    if not records:
        return []
    latest_date = max(r.bucket_ts.date() for r in records)
    recent_start = latest_date - timedelta(days=recent_days - 1)
    previous_start = recent_start - timedelta(days=recent_days)
    previous_end = recent_start - timedelta(days=1)

    recent_totals: dict[str, Decimal] = {}
    previous_totals: dict[str, Decimal] = {}
    for r in records:
        value = getattr(r, dimension) or "(none)"
        d = r.bucket_ts.date()
        if recent_start <= d <= latest_date:
            recent_totals[value] = recent_totals.get(value, Decimal(0)) + r.cost_usd
        elif previous_start <= d <= previous_end:
            previous_totals[value] = previous_totals.get(value, Decimal(0)) + r.cost_usd

    rows = []
    for value in set(recent_totals) | set(previous_totals):
        recent_cost = recent_totals.get(value, Decimal(0))
        previous_cost = previous_totals.get(value, Decimal(0))
        delta = recent_cost - previous_cost
        pct_change = float(delta / previous_cost) if previous_cost > 0 else None
        rows.append(
            MoverRow(value=value, recent_cost=recent_cost, previous_cost=previous_cost, delta=delta, pct_change=pct_change)
        )
    rows.sort(key=lambda row: abs(row.delta), reverse=True)
    return rows
