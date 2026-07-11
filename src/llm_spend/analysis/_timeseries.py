"""Shared daily-aggregation helper for attribution/forecast/risk."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from llm_spend.schema import UsageRecord


def daily_totals(records: list[UsageRecord]) -> dict[date, Decimal]:
    """Sum cost_usd per UTC calendar date."""
    totals: dict[date, Decimal] = {}
    for r in records:
        d = r.bucket_ts.date()
        totals[d] = totals.get(d, Decimal(0)) + r.cost_usd
    return totals
