import stat
from datetime import datetime, timezone

from llm_spend import cache
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


def test_write_then_read_round_trips(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    records = [_record(), _record(model="gpt-5.4-mini", api_key_id="key_a")]

    cache.write_records("openai", records, cache_dir=cache_dir)
    read_back = cache.read_records("openai", cache_dir=cache_dir)

    assert read_back == records


def test_cache_dir_self_gitignores(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    cache.write_records("openai", [_record()], cache_dir=cache_dir)

    gitignore = cache_dir / ".gitignore"
    assert gitignore.exists()
    assert gitignore.read_text() == "*\n"


def test_cache_file_is_0600(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    path = cache.write_records("openai", [_record()], cache_dir=cache_dir)

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_read_records_missing_file_returns_empty(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    assert cache.read_records("openai", cache_dir=cache_dir) == []


def test_write_then_read_reconciliation_total(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    until = datetime(2026, 6, 30, tzinfo=timezone.utc)

    cache.write_reconciliation_total("openai", 123.45, since, until, cache_dir=cache_dir)
    total = cache.read_reconciliation_total("openai", cache_dir=cache_dir)

    assert total == 123.45


def test_reconciliation_total_file_is_0600(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    path = cache.write_reconciliation_total("openai", 1.0, since, None, cache_dir=cache_dir)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_read_reconciliation_total_missing_file_returns_none(tmp_path):
    cache_dir = tmp_path / ".llm-spend-cache"
    assert cache.read_reconciliation_total("openai", cache_dir=cache_dir) is None
