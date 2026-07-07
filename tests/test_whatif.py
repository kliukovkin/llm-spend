from llm_spend.analysis import whatif
from tests.conftest import make_record

PRICING = {
    "openai": {
        "gpt-5.4-mini": {"input": 0.75, "output": 4.50, "batch_input": 0.375, "batch_output": 2.25},
        "gpt-5.5": {"input": 5.00, "output": 30.00},  # no batch pricing on purpose
    }
}


def test_batch_gap_computes_hypothetical_savings():
    records = [
        make_record(model="gpt-5.4-mini", batch_flag=False, input_tokens=1_000_000, output_tokens=1_000_000, cost_usd=5.25)
    ]
    rows = whatif.batch_gap(records, PRICING)

    assert len(rows) == 1
    row = rows[0]
    assert row.model == "gpt-5.4-mini"
    # hypothetical: 1M * 0.375/1M + 1M * 2.25/1M = 0.375 + 2.25 = 2.625
    assert row.hypothetical_batch_cost == 2.625
    assert row.actual_cost == 5.25
    assert row.potential_savings == 5.25 - 2.625


def test_batch_gap_excludes_already_batched_usage():
    records = [make_record(model="gpt-5.4-mini", batch_flag=True, cost_usd=1.0)]
    assert whatif.batch_gap(records, PRICING) == []


def test_batch_gap_skips_models_without_batch_pricing():
    records = [make_record(model="gpt-5.5", batch_flag=False, cost_usd=1.0)]
    assert whatif.batch_gap(records, PRICING) == []


def test_batch_gap_skips_models_missing_from_pricing_entirely():
    records = [make_record(model="some-unknown-model", batch_flag=False, cost_usd=1.0)]
    assert whatif.batch_gap(records, PRICING) == []


def test_service_tier_gap_compares_realized_cost_per_token():
    records = [
        make_record(model="m", service_tier="standard", input_tokens=1000, output_tokens=0, cost_usd=2.0),
        make_record(model="m", service_tier="priority", input_tokens=1000, output_tokens=0, cost_usd=4.0),
    ]
    result = whatif.service_tier_gap(records)

    assert "m" in result
    rows = result["m"]
    assert rows[0].service_tier == "standard"  # cheaper tier sorts first
    assert rows[0].cost_per_1k_tokens == 2.0
    assert rows[1].service_tier == "priority"
    assert rows[1].cost_per_1k_tokens == 4.0


def test_service_tier_gap_excludes_models_with_only_one_tier():
    records = [make_record(model="m", service_tier="standard", cost_usd=1.0)]
    assert whatif.service_tier_gap(records) == {}


def test_service_tier_gap_ignores_records_without_a_tier():
    records = [make_record(model="m", service_tier=None, cost_usd=1.0)]
    assert whatif.service_tier_gap(records) == {}


def test_cache_hit_rate():
    records = [
        make_record(model="m", input_tokens=1000, cached_tokens=250),
        make_record(model="m", input_tokens=1000, cached_tokens=250),
    ]
    rows = whatif.cache_hit_rate(records)
    assert len(rows) == 1
    assert rows[0].model == "m"
    assert rows[0].input_tokens == 2000
    assert rows[0].cached_tokens == 500
    assert rows[0].hit_rate == 0.25


def test_cache_hit_rate_skips_models_with_zero_input_tokens():
    records = [make_record(model="m", input_tokens=0, cached_tokens=0)]
    assert whatif.cache_hit_rate(records) == []
