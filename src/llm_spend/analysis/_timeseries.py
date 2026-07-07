"""Shared daily-aggregation helper for attribution/forecast/risk."""

from __future__ import annotations

from datetime import date

from llm_spend.schema import UsageRecord


def daily_totals(records: list[UsageRecord]) -> dict[date, float]:
    """Sum cost_usd per UTC calendar date."""
    totals: dict[date, float] = {}
    for r in records:
        d = r.bucket_ts.date()
        totals[d] = totals.get(d, 0.0) + r.cost_usd
    return totals
