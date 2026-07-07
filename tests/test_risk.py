from datetime import date, datetime, timedelta, timezone

import synth_data

from llm_spend.analysis import risk
from tests.conftest import make_record


def test_overspend_scenario_uses_most_expensive_day():
    records = [
        make_record(bucket_ts=datetime(2026, 6, 1, tzinfo=timezone.utc), cost_usd=1.0),
        make_record(bucket_ts=datetime(2026, 6, 15, tzinfo=timezone.utc), cost_usd=20.0),  # June has 30 days
    ]
    scenario = risk.overspend_scenario(records)

    assert scenario.most_expensive_day == date(2026, 6, 15)
    assert scenario.most_expensive_day_cost == 20.0
    assert scenario.days_in_month == 30
    assert scenario.worst_case_projection == 600.0
    assert "hard spending cap" in scenario.note


def test_overspend_scenario_empty_records_returns_none():
    assert risk.overspend_scenario([]) is None


def test_detect_anomalies_reports_insufficient_history_below_21_days():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=start + timedelta(days=i), cost_usd=1.0) for i in range(20)]

    result = risk.detect_anomalies(records)

    assert result.insufficient_history is True
    assert result.days_of_history == 20
    assert result.anomalies == []
    assert "21" in result.note


def test_detect_anomalies_no_flags_when_costs_are_uniform():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=start + timedelta(days=i), cost_usd=5.0) for i in range(28)]
    result = risk.detect_anomalies(records)
    assert result.anomalies == []


def _spike_at_day_22(daily_cost: float, spike_cost: float) -> list:
    """22 days: baseline `daily_cost`/day, spiked to `spike_cost` on day 22
    (the earliest a spike can appear right after the 21-day minimum turns
    the feature on) — day 22 lands on the same weekday as day 1, 8, 15."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = []
    for i in range(22):
        cost = spike_cost if i == 21 else daily_cost
        records.append(make_record(bucket_ts=start + timedelta(days=i), cost_usd=cost))
    return records


def test_detect_anomalies_flags_injected_spike_at_day_22_personal_scale():
    records = _spike_at_day_22(daily_cost=1.0, spike_cost=20.0)
    result = risk.detect_anomalies(records)

    assert result.insufficient_history is False
    flagged_days = {a.day for a in result.anomalies}
    day_22 = date(2026, 6, 22)
    assert day_22 in flagged_days
    spike = next(a for a in result.anomalies if a.day == day_22)
    assert spike.z_score == float("inf")  # baseline reference is perfectly uniform
    assert spike.reference_count == 3  # days 1, 8, 15 (day 22 excludes itself)
    assert spike.confidence == risk.LOW_CONFIDENCE  # 3 < MIN_REFERENCE_FOR_CONFIDENCE


def test_detect_anomalies_flags_injected_spike_at_day_22_team_scale():
    records = _spike_at_day_22(daily_cost=800.0, spike_cost=5000.0)
    result = risk.detect_anomalies(records)

    flagged_days = {a.day for a in result.anomalies}
    assert date(2026, 6, 22) in flagged_days


def test_detect_anomalies_materiality_floor_suppresses_tiny_absolute_moves():
    # z-score can be huge on a near-zero, near-uniform history even though
    # the absolute move is trivial — the materiality floor should suppress it.
    records = _spike_at_day_22(daily_cost=0.02, spike_cost=0.08)
    result = risk.detect_anomalies(records)
    assert result.anomalies == []


def test_detect_anomalies_zero_flags_on_normal_weekly_variation_personal_scale():
    records = synth_data.generate_personal(seed=0, days=60, inject_spike=False)
    result = risk.detect_anomalies(records)
    assert result.anomalies == []


def test_detect_anomalies_zero_flags_on_normal_weekly_variation_team_scale():
    records = synth_data.generate_team(seed=1, days=60, inject_spike=False)
    result = risk.detect_anomalies(records)
    assert result.anomalies == []
