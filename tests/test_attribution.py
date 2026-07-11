from datetime import datetime, timedelta, timezone
from decimal import Decimal

import synth_data

from llm_spend.analysis import attribution
from tests.conftest import make_record


def test_breakdown_sums_and_shares_by_model():
    records = [
        make_record(model="gpt-5.4-mini", cost_usd=3.0),
        make_record(model="gpt-5.4-mini", cost_usd=1.0),
        make_record(model="gpt-5.4", cost_usd=6.0),
    ]
    rows = attribution.breakdown(records, "model")

    assert [r.value for r in rows] == ["gpt-5.4", "gpt-5.4-mini"]
    assert rows[0].cost_usd == 6.0
    assert rows[0].share == 0.6
    assert rows[1].cost_usd == 4.0
    assert rows[1].share == 0.4


def test_breakdown_groups_none_values_together():
    records = [make_record(api_key_id=None, cost_usd=1.0), make_record(api_key_id=None, cost_usd=2.0)]
    rows = attribution.breakdown(records, "api_key_id")
    assert len(rows) == 1
    assert rows[0].value == "(none)"
    assert rows[0].cost_usd == 3.0


def test_total_cost():
    records = [make_record(cost_usd=1.5), make_record(cost_usd=2.5)]
    assert attribution.total_cost(records) == 4.0


def test_most_expensive_day():
    day1 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    day2 = datetime(2026, 6, 2, tzinfo=timezone.utc)
    records = [
        make_record(bucket_ts=day1, cost_usd=1.0),
        make_record(bucket_ts=day2, cost_usd=5.0),
    ]
    day, cost = attribution.most_expensive_day(records)
    assert day == day2.date()
    assert cost == 5.0


def test_most_expensive_day_empty_records():
    assert attribution.most_expensive_day([]) is None


def test_top_movers_detects_increase_and_decrease():
    latest = datetime(2026, 6, 14, tzinfo=timezone.utc)  # recent window: 6/8-6/14, previous: 6/1-6/7
    records = []
    for offset in range(7):
        # "up" key doubles in the recent window; "down" key halves.
        records.append(make_record(bucket_ts=latest - timedelta(days=offset), api_key_id="up", cost_usd=2.0))
        records.append(make_record(bucket_ts=latest - timedelta(days=offset + 7), api_key_id="up", cost_usd=1.0))
        records.append(make_record(bucket_ts=latest - timedelta(days=offset), api_key_id="down", cost_usd=1.0))
        records.append(make_record(bucket_ts=latest - timedelta(days=offset + 7), api_key_id="down", cost_usd=2.0))

    rows = attribution.top_movers(records, "api_key_id", recent_days=7)
    by_key = {r.value: r for r in rows}

    assert by_key["up"].recent_cost == 14.0
    assert by_key["up"].previous_cost == 7.0
    assert by_key["up"].delta == 7.0
    assert by_key["up"].pct_change == 1.0

    assert by_key["down"].recent_cost == 7.0
    assert by_key["down"].previous_cost == 14.0
    assert by_key["down"].delta == -7.0


def test_top_movers_pct_change_none_when_no_previous_baseline():
    latest = datetime(2026, 6, 14, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=latest, api_key_id="new", cost_usd=5.0)]
    rows = attribution.top_movers(records, "api_key_id", recent_days=7)
    assert rows[0].pct_change is None
    assert rows[0].previous_cost == 0.0


def test_breakdown_sums_match_total_on_synthetic_data():
    records = synth_data.generate_team(seed=1, days=60)
    rows = attribution.breakdown(records, "api_key_id")
    # Decimal, unlike float, sums exactly regardless of summation order, so
    # this is an exact-equality check, not pytest.approx.
    assert sum((r.cost_usd for r in rows), start=Decimal(0)) == attribution.total_cost(records)


def test_most_expensive_day_is_the_injected_spike_on_synthetic_data():
    records = synth_data.generate_personal(seed=0, days=60)
    day, cost = attribution.most_expensive_day(records)
    daily = {}
    for r in records:
        d = r.bucket_ts.date()
        daily[d] = daily.get(d, Decimal(0)) + r.cost_usd
    median_cost = sorted(daily.values())[len(daily) // 2]
    assert cost > median_cost * 2  # the injected spike stands out sharply
