from datetime import date, datetime, timedelta, timezone

from llm_spend.analysis import forecast
from tests.conftest import make_record


def test_forecast_linear_projection():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)  # June has 30 days
    records = [make_record(bucket_ts=start + timedelta(days=i), cost_usd=10.0) for i in range(10)]

    result = forecast.forecast_month_end(records)

    assert result.days_elapsed == 10
    assert result.days_in_month == 30
    assert result.spend_so_far == 100.0
    assert result.daily_average == 10.0
    assert result.projected_total == 300.0
    assert "rough estimate" in result.disclaimer.lower()


def test_forecast_defaults_as_of_to_latest_record():
    records = [
        make_record(bucket_ts=datetime(2026, 6, 1, tzinfo=timezone.utc), cost_usd=5.0),
        make_record(bucket_ts=datetime(2026, 6, 5, tzinfo=timezone.utc), cost_usd=5.0),
    ]
    result = forecast.forecast_month_end(records)
    assert result.days_elapsed == 5  # as_of defaults to June 5


def test_forecast_empty_records_returns_none():
    assert forecast.forecast_month_end([]) is None


def test_forecast_as_of_month_with_no_data_returns_none():
    records = [make_record(bucket_ts=datetime(2026, 6, 1, tzinfo=timezone.utc), cost_usd=5.0)]
    result = forecast.forecast_month_end(records, as_of=date(2026, 7, 15))
    assert result is None


def test_forecast_only_counts_records_within_the_as_of_month():
    records = [
        make_record(bucket_ts=datetime(2026, 5, 31, tzinfo=timezone.utc), cost_usd=100.0),  # previous month
        make_record(bucket_ts=datetime(2026, 6, 1, tzinfo=timezone.utc), cost_usd=10.0),
    ]
    result = forecast.forecast_month_end(records, as_of=date(2026, 6, 1))
    assert result.spend_so_far == 10.0
    assert result.days_elapsed == 1
