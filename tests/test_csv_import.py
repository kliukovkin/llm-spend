from datetime import datetime, timezone
from decimal import Decimal

import pytest

from llm_spend.connectors import csv_import


def _write(tmp_path, content):
    path = tmp_path / "usage.csv"
    path.write_text(content)
    return path


def test_parses_required_columns_only(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd\n"
        "2026-06-01,openai,gpt-5.4-mini,1000,200,0.01\n",
    )
    records = csv_import.parse_csv(path)

    assert len(records) == 1
    r = records[0]
    assert r.bucket_ts == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert r.provider == "openai"
    assert r.model == "gpt-5.4-mini"
    assert r.input_tokens == 1000
    assert r.output_tokens == 200
    assert r.cost_usd == Decimal("0.01")
    assert r.api_key_id is None
    assert r.batch_flag is False
    assert r.cached_tokens == 0


def test_parses_all_optional_columns(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd,api_key_id,project,service_tier,batch_flag,cached_tokens\n"
        "2026-06-01,anthropic,claude-sonnet-5,1000,200,0.05,key_a,proj_a,priority,true,300\n",
    )
    records = csv_import.parse_csv(path)

    r = records[0]
    assert r.api_key_id == "key_a"
    assert r.project == "proj_a"
    assert r.service_tier == "priority"
    assert r.batch_flag is True
    assert r.cached_tokens == 300


def test_full_datetime_with_explicit_timezone_is_normalized_to_utc(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd\n"
        "2026-06-01T05:00:00+03:00,openai,gpt-5.4-mini,1000,200,0.01\n",
    )
    records = csv_import.parse_csv(path)
    assert records[0].bucket_ts == datetime(2026, 6, 1, 2, 0, 0, tzinfo=timezone.utc)


def test_missing_required_column_raises(tmp_path):
    path = _write(tmp_path, "bucket_ts,provider,model,input_tokens,output_tokens\n2026-06-01,openai,gpt-5.4-mini,1000,200\n")
    with pytest.raises(csv_import.CSVImportError, match="cost_usd"):
        csv_import.parse_csv(path)


def test_empty_file_raises(tmp_path):
    path = _write(tmp_path, "")
    with pytest.raises(csv_import.CSVImportError, match="empty file"):
        csv_import.parse_csv(path)


def test_invalid_provider_raises_with_row_number(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd\n"
        "2026-06-01,openai,gpt-5.4-mini,1000,200,0.01\n"
        "2026-06-02,notaprovider,gpt-5.4-mini,1000,200,0.01\n",
    )
    with pytest.raises(csv_import.CSVImportError, match="row 3.*notaprovider"):
        csv_import.parse_csv(path)


def test_malformed_number_raises_with_row_number(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd\n"
        "2026-06-01,openai,gpt-5.4-mini,not-a-number,200,0.01\n",
    )
    with pytest.raises(csv_import.CSVImportError, match="row 2"):
        csv_import.parse_csv(path)


def test_invalid_bucket_ts_raises(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd\nnot-a-date,openai,gpt-5.4-mini,1000,200,0.01\n",
    )
    with pytest.raises(csv_import.CSVImportError, match="invalid bucket_ts"):
        csv_import.parse_csv(path)


def test_multiple_rows_parsed_in_order(tmp_path):
    path = _write(
        tmp_path,
        "bucket_ts,provider,model,input_tokens,output_tokens,cost_usd\n"
        "2026-06-01,openai,gpt-5.4-mini,1000,200,0.01\n"
        "2026-06-02,anthropic,claude-haiku-4-5,500,100,0.02\n",
    )
    records = csv_import.parse_csv(path)
    assert len(records) == 2
    assert records[0].provider == "openai"
    assert records[1].provider == "anthropic"
