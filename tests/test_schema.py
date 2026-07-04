from datetime import datetime, timezone

import pytest

from llm_spend.schema import UsageRecord


def _record(**overrides):
    defaults = dict(
        bucket_ts=datetime(2026, 6, 1, tzinfo=timezone.utc),
        provider="openai",
        model="gpt-5.4",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.0055,
    )
    defaults.update(overrides)
    return UsageRecord(**defaults)


def test_minimal_record_has_defaults():
    record = _record()
    assert record.cached_tokens == 0
    assert record.batch_flag is False
    assert record.api_key_id is None
    assert record.project is None
    assert record.service_tier is None


def test_full_record_round_trips_fields():
    record = _record(
        api_key_id="key_abc",
        project="proj_x",
        service_tier="scale",
        batch_flag=True,
        cached_tokens=100,
    )
    assert record.api_key_id == "key_abc"
    assert record.project == "proj_x"
    assert record.service_tier == "scale"
    assert record.batch_flag is True
    assert record.cached_tokens == 100


def test_record_is_frozen():
    record = _record()
    with pytest.raises(AttributeError):
        record.cost_usd = 1.0


def test_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        _record(bucket_ts=datetime(2026, 6, 1))


def test_rejects_non_utc_timestamp():
    from datetime import timedelta

    tz = timezone(timedelta(hours=3))
    with pytest.raises(ValueError, match="UTC"):
        _record(bucket_ts=datetime(2026, 6, 1, tzinfo=tz))


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cached_tokens"])
def test_rejects_negative_token_counts(field):
    with pytest.raises(ValueError, match="must be >= 0"):
        _record(**{field: -1})


def test_rejects_negative_cost():
    with pytest.raises(ValueError, match="cost_usd must be >= 0"):
        _record(cost_usd=-0.01)


def test_rejects_cached_tokens_exceeding_input_tokens():
    with pytest.raises(ValueError, match="cannot exceed"):
        _record(input_tokens=100, cached_tokens=101)
