"""CSV import: normalizes a generic usage-export CSV into UsageRecord.

This is the low-trust on-ramp alongside admin API keys (see design docs:
v0.1 wants both a credentialed path and a no-credentials path) — no admin
key needed, just a file. The columns below are llm-spend's own generic
schema, not any specific provider's native export format; documented in
the README so someone can produce one from whatever their provider's
console actually exports, or write one by hand for a handful of rows.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from llm_spend.schema import UsageRecord

REQUIRED_COLUMNS = ["bucket_ts", "provider", "model", "input_tokens", "output_tokens", "cost_usd"]
OPTIONAL_COLUMNS = ["api_key_id", "project", "service_tier", "batch_flag", "cached_tokens"]
VALID_PROVIDERS = {"openai", "anthropic"}
TRUE_VALUES = {"true", "1", "yes"}


class CSVImportError(RuntimeError):
    """Raised when the file is missing required columns, or a row can't
    be parsed into a UsageRecord."""


def _parse_bucket_ts(value: str) -> datetime:
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid bucket_ts {value!r} (expected an ISO date or datetime)") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"invalid provider {value!r} (expected one of {sorted(VALID_PROVIDERS)})")
    return provider


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def _row_to_record(row: dict[str, str], line_number: int) -> UsageRecord:
    try:
        return UsageRecord(
            bucket_ts=_parse_bucket_ts(row["bucket_ts"]),
            provider=_parse_provider(row["provider"]),
            model=row["model"].strip(),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cost_usd=float(row["cost_usd"]),
            api_key_id=row.get("api_key_id") or None,
            project=row.get("project") or None,
            service_tier=row.get("service_tier") or None,
            batch_flag=_parse_bool(row["batch_flag"]) if row.get("batch_flag") else False,
            cached_tokens=int(row["cached_tokens"]) if row.get("cached_tokens") else 0,
        )
    except (ValueError, TypeError) as exc:
        raise CSVImportError(f"row {line_number}: {exc}") from exc


def parse_csv(path: Path) -> list[UsageRecord]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise CSVImportError(f"{path}: empty file, no header row")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise CSVImportError(f"{path}: missing required column(s): {', '.join(missing)}")

        records = []
        for line_number, row in enumerate(reader, start=2):  # header is line 1
            records.append(_row_to_record(row, line_number))
        return records
