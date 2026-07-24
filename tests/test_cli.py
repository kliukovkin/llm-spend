from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typer.testing import CliRunner

from llm_spend import cache
from llm_spend.cli import _filter_records_by_window, app
from tests.conftest import make_record


runner = CliRunner()


def test_filter_records_by_window_uses_inclusive_since_exclusive_until():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=start + timedelta(days=i)) for i in range(5)]

    filtered = _filter_records_by_window(
        records,
        since=datetime(2026, 6, 2, tzinfo=timezone.utc),
        until=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert [r.bucket_ts.date().isoformat() for r in filtered] == ["2026-06-02", "2026-06-03"]


def test_report_since_until_filters_cached_records_and_keeps_short_history_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=start + timedelta(days=i), cost_usd=1.0) for i in range(30)]
    cache.write_records("openai", records)

    result = runner.invoke(app, ["report", "--since", "2026-06-03", "--until", "2026-06-08"])

    assert result.exit_code == 0
    assert "Total spend" in result.output
    assert "$5.00" in result.output
    assert "Only 5 days of history" in result.output


def test_report_filtered_window_does_not_compare_against_unfiltered_reconciliation_total(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=start + timedelta(days=i), cost_usd=1.0) for i in range(30)]
    cache.write_records("openai", records)
    cache.write_reconciliation_total(
        "openai",
        total_usd=Decimal("30.0"),
        since=start,
        until=start + timedelta(days=30),
    )

    result = runner.invoke(app, ["report", "--since", "2026-06-03", "--until", "2026-06-08"])

    assert result.exit_code == 0
    assert "billing dashboard total diverges" not in result.output


def test_report_errors_when_filters_match_no_cached_records(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache.write_records("openai", [make_record()])

    result = runner.invoke(app, ["report", "--since", "2026-07-01"])

    assert result.exit_code == 1
    assert "No cached usage data found for the requested report window" in result.output
