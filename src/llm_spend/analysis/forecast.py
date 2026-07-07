"""Naive linear forecast to end of the current UTC month.

Straight-line projection of the daily average onto the rest of the month —
no seasonality, no day-of-week weighting. That's a deliberate v0.1
boundary, not an oversight: seasonal/weekday-aware forecasting is out of
scope until real usage data justifies it. Always paired with an explicit
disclaimer so the report never states this as a confident number.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from llm_spend.analysis._timeseries import daily_totals
from llm_spend.schema import UsageRecord

DISCLAIMER = (
    "Rough estimate: a straight-line projection of your daily average onto "
    "the rest of the month. It has no idea about weekday patterns, one-off "
    "spikes, or seasonality — treat it as a ballpark, not a bill."
)


@dataclass(frozen=True, slots=True)
class ForecastResult:
    days_elapsed: int
    days_in_month: int
    spend_so_far: float
    daily_average: float
    projected_total: float
    disclaimer: str = DISCLAIMER


def forecast_month_end(records: list[UsageRecord], as_of: date | None = None) -> ForecastResult | None:
    """`as_of` defaults to the latest date present in `records` — the month
    forecast is always for *that* date's month, not necessarily the
    real-world current month (useful for synthetic/historical data)."""
    totals = daily_totals(records)
    if not totals:
        return None
    as_of = as_of or max(totals)

    month_totals = {d: cost for d, cost in totals.items() if d.year == as_of.year and d.month == as_of.month}
    if not month_totals:
        return None

    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    days_elapsed = as_of.day
    spend_so_far = sum(month_totals.values())
    daily_average = spend_so_far / days_elapsed
    return ForecastResult(
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        spend_so_far=spend_so_far,
        daily_average=daily_average,
        projected_total=daily_average * days_in_month,
    )
