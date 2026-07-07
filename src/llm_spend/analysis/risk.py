"""Overspend-scenario framing and same-weekday anomaly detection.

Neither the forecast nor pricing.yaml enforce any actual spending limit —
that's the point of the overspend scenario here: OpenAI and Anthropic don't
impose a hard cap by default, so "what if your worst day repeated" is a
more honest risk framing than the linear forecast alone.

Anomalies compare a day's spend against *the same weekday's* history, not
a flat all-days average — a Saturday running 3x a weekday's cost is
normal, not anomalous. Below 21 days of history overall we say so plainly
instead of computing anything on too little data to be meaningful (a false
alarm in someone's first report kills trust faster than the feature being
absent).

The z-score is leave-one-out: each day is compared to its weekday's *other*
occurrences, excluding itself. A naive in-sample z-score (mean/stddev
computed over all points including the one being tested) has a fatal flaw
for small samples — a single huge outlier inflates its own stddev enough
to cap its own z-score at n/sqrt(n+1) regardless of magnitude (n=2 other
points -> ceiling 1.15, which no threshold can reliably clear). LOO removes
that self-referential bias entirely, so detection is mathematically
possible right at the 21-day minimum (3 same-weekday samples -> 2
reference points).

That still leaves 2-4 reference points as a statistically shaky basis for
a hard verdict, so there are two additional guardrails, not a hard gate:
  1. Materiality floor: even a huge z-score doesn't flag a day unless its
     cost also clears max(1.5x the reference median, reference median +
     absolute_floor). This stops a shift from $0.02 to $0.08 (huge z on a
     near-zero, near-uniform history) from reading as a spend "anomaly".
  2. Confidence tiering: with fewer than MIN_REFERENCE_FOR_CONFIDENCE
     reference points, a finding is still reported but labeled low
     confidence rather than presented as a flat "anomaly" — honest about
     the sample size instead of silently withholding the finding.
"""

from __future__ import annotations

import calendar
import statistics
from dataclasses import dataclass, field
from datetime import date

from llm_spend.analysis import attribution
from llm_spend.analysis._timeseries import daily_totals
from llm_spend.schema import UsageRecord

MIN_HISTORY_DAYS = 21
Z_SCORE_THRESHOLD = 2.5
DEFAULT_ABSOLUTE_FLOOR_USD = 5.0
MIN_REFERENCE_FOR_CONFIDENCE = 5

NORMAL_CONFIDENCE = "normal"
LOW_CONFIDENCE = "low confidence — limited history"

OVERSPEND_NOTE = (
    "Neither OpenAI nor Anthropic enforces a hard spending cap by default — "
    "usage can keep accruing past whatever number you have in mind. This is "
    "what your worst day repeated every day this month would cost, not a "
    "prediction."
)


@dataclass(frozen=True, slots=True)
class OverspendScenario:
    most_expensive_day: date
    most_expensive_day_cost: float
    days_in_month: int
    worst_case_projection: float
    note: str = OVERSPEND_NOTE


def overspend_scenario(records: list[UsageRecord], as_of: date | None = None) -> OverspendScenario | None:
    worst_day = attribution.most_expensive_day(records)
    if worst_day is None:
        return None
    day, cost = worst_day
    as_of = as_of or day
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    return OverspendScenario(
        most_expensive_day=day,
        most_expensive_day_cost=cost,
        days_in_month=days_in_month,
        worst_case_projection=cost * days_in_month,
    )


@dataclass(frozen=True, slots=True)
class Anomaly:
    day: date
    cost_usd: float
    reference_mean: float
    reference_median: float
    reference_stddev: float
    reference_count: int
    z_score: float
    confidence: str


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    anomalies: list[Anomaly] = field(default_factory=list)
    insufficient_history: bool = False
    days_of_history: int = 0
    note: str = ""


def detect_anomalies(
    records: list[UsageRecord],
    z_threshold: float = Z_SCORE_THRESHOLD,
    absolute_floor: float = DEFAULT_ABSOLUTE_FLOOR_USD,
    min_reference_for_confidence: int = MIN_REFERENCE_FOR_CONFIDENCE,
) -> AnomalyResult:
    totals = daily_totals(records)
    days_of_history = len(totals)
    if days_of_history < MIN_HISTORY_DAYS:
        return AnomalyResult(
            insufficient_history=True,
            days_of_history=days_of_history,
            note=(
                f"Only {days_of_history} days of history — need at least "
                f"{MIN_HISTORY_DAYS} to compare same-weekday spend reliably. "
                "No anomaly check run."
            ),
        )

    by_weekday: dict[int, list[tuple[date, float]]] = {}
    for day, cost in totals.items():
        by_weekday.setdefault(day.weekday(), []).append((day, cost))

    anomalies = []
    for day_costs in by_weekday.values():
        for target_day, target_cost in day_costs:
            reference = [c for d, c in day_costs if d != target_day]
            if len(reference) < 2:
                continue  # can't compute a stddev from fewer than 2 points

            ref_mean = statistics.mean(reference)
            ref_median = statistics.median(reference)
            ref_stddev = statistics.stdev(reference)

            if ref_stddev == 0:
                z = float("inf") if target_cost != ref_mean else 0.0
            else:
                z = (target_cost - ref_mean) / ref_stddev

            materiality_floor = max(1.5 * ref_median, ref_median + absolute_floor)
            if z > z_threshold and target_cost > materiality_floor:
                confidence = LOW_CONFIDENCE if len(reference) < min_reference_for_confidence else NORMAL_CONFIDENCE
                anomalies.append(
                    Anomaly(
                        day=target_day,
                        cost_usd=target_cost,
                        reference_mean=ref_mean,
                        reference_median=ref_median,
                        reference_stddev=ref_stddev,
                        reference_count=len(reference),
                        z_score=z,
                        confidence=confidence,
                    )
                )

    anomalies.sort(key=lambda a: a.day)
    return AnomalyResult(anomalies=anomalies, insufficient_history=False, days_of_history=days_of_history)
