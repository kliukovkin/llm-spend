"""OpenAI admin API connector: usage/completions + costs, joined into UsageRecord.

Requires an organization Admin API key (not a project key) — see
https://platform.openai.com/docs/api-reference for scope details.

The Costs API doesn't break spend down by model/batch/service_tier the way
Usage does (it only groups by project_id/api_key_id/line_item), so a single
cost bucket can cover several usage rows. We allocate each cost bucket's
dollar total across its matching usage rows in proportion to token volume.
That's a heuristic for the per-model split, but because it's a proportional
split of the same total, the sum for any (bucket, project, key) reconciles
exactly against the Costs API — which is what the report's reconciliation
check actually needs (see docs on the >1% divergence flag).

Cost buckets with no matching usage rows (e.g. spend on non-completions
products within the same project/key) still become a record, tagged
model="other", so no dollar amount is silently dropped from the total.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from llm_spend.schema import UsageRecord

BASE_URL = "https://api.openai.com/v1"
USAGE_PATH = "/organization/usage/completions"
COSTS_PATH = "/organization/costs"

USAGE_GROUP_BY = ["project_id", "api_key_id", "model", "batch", "service_tier"]
COSTS_GROUP_BY = ["project_id", "api_key_id"]

MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAIAdminAPIError(RuntimeError):
    """Raised when the OpenAI admin API returns a non-retryable error, or
    retries are exhausted on a retryable one."""


@dataclass(frozen=True, slots=True)
class _UsageRow:
    bucket_start: datetime
    project_id: str | None
    api_key_id: str | None
    model: str | None
    batch: bool | None
    service_tier: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int


@dataclass(frozen=True, slots=True)
class _CostRow:
    bucket_start: datetime
    project_id: str | None
    api_key_id: str | None
    amount_usd: float


def _get_with_backoff(client: httpx.Client, path: str, params: dict) -> dict:
    for attempt in range(MAX_RETRIES):
        response = client.get(path, params=params)
        if response.status_code in RETRYABLE_STATUS:
            if attempt == MAX_RETRIES - 1:
                raise OpenAIAdminAPIError(
                    f"{path} failed after {MAX_RETRIES} attempts: {response.status_code} {response.text}"
                )
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after else 2**attempt
            time.sleep(delay)
            continue
        if response.status_code >= 400:
            raise OpenAIAdminAPIError(f"{path} returned {response.status_code}: {response.text}")
        return response.json()
    raise OpenAIAdminAPIError(f"exhausted retries for {path}")  # unreachable, keeps type-checkers happy


def _paginate(client: httpx.Client, path: str, params: dict) -> Iterator[dict]:
    """Yield every time bucket across all pages of a usage/costs endpoint."""
    page_params = dict(params)
    while True:
        payload = _get_with_backoff(client, path, page_params)
        yield from payload["data"]
        if not payload.get("has_more"):
            return
        page_params = dict(params, page=payload["next_page"])


def _time_range_params(since: datetime, until: datetime | None) -> dict:
    params: dict = {
        "start_time": int(since.timestamp()),
        "bucket_width": "1d",
        "limit": 180,
    }
    if until is not None:
        params["end_time"] = int(until.timestamp())
    return params


def _fetch_usage_rows(client: httpx.Client, since: datetime, until: datetime | None) -> list[_UsageRow]:
    params = _time_range_params(since, until)
    params["group_by"] = USAGE_GROUP_BY
    rows = []
    for bucket in _paginate(client, USAGE_PATH, params):
        bucket_start = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc)
        for result in bucket["results"]:
            rows.append(
                _UsageRow(
                    bucket_start=bucket_start,
                    project_id=result.get("project_id"),
                    api_key_id=result.get("api_key_id"),
                    model=result.get("model"),
                    batch=result.get("batch"),
                    service_tier=result.get("service_tier"),
                    input_tokens=result.get("input_tokens", 0),
                    output_tokens=result.get("output_tokens", 0),
                    cached_tokens=result.get("input_cached_tokens", 0),
                )
            )
    return rows


def _fetch_cost_rows(client: httpx.Client, since: datetime, until: datetime | None) -> list[_CostRow]:
    params = _time_range_params(since, until)
    params["group_by"] = COSTS_GROUP_BY
    rows = []
    for bucket in _paginate(client, COSTS_PATH, params):
        bucket_start = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc)
        for result in bucket["results"]:
            rows.append(
                _CostRow(
                    bucket_start=bucket_start,
                    project_id=result.get("project_id"),
                    api_key_id=result.get("api_key_id"),
                    amount_usd=result["amount"]["value"],
                )
            )
    return rows


def _join_key(bucket_start: datetime, project_id: str | None, api_key_id: str | None) -> tuple:
    return (bucket_start, project_id, api_key_id)


def _allocate_cost(usage_rows: list[_UsageRow], cost_rows: list[_CostRow]) -> list[UsageRecord]:
    cost_by_key: dict[tuple, float] = {}
    for row in cost_rows:
        key = _join_key(row.bucket_start, row.project_id, row.api_key_id)
        cost_by_key[key] = cost_by_key.get(key, 0.0) + row.amount_usd

    usage_by_key: dict[tuple, list[_UsageRow]] = {}
    for row in usage_rows:
        key = _join_key(row.bucket_start, row.project_id, row.api_key_id)
        usage_by_key.setdefault(key, []).append(row)

    records = []
    for key, rows in usage_by_key.items():
        total_cost = cost_by_key.get(key, 0.0)
        total_tokens = sum(r.input_tokens + r.output_tokens for r in rows) or 1
        for row in rows:
            share = (row.input_tokens + row.output_tokens) / total_tokens
            records.append(
                UsageRecord(
                    bucket_ts=row.bucket_start,
                    provider="openai",
                    model=row.model or "unknown",
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    cost_usd=round(total_cost * share, 6),
                    api_key_id=row.api_key_id,
                    project=row.project_id,
                    service_tier=row.service_tier,
                    batch_flag=bool(row.batch),
                    cached_tokens=row.cached_tokens,
                )
            )

    for key, total_cost in cost_by_key.items():
        if key in usage_by_key:
            continue
        bucket_start, project_id, api_key_id = key
        records.append(
            UsageRecord(
                bucket_ts=bucket_start,
                provider="openai",
                model="other",
                input_tokens=0,
                output_tokens=0,
                cost_usd=round(total_cost, 6),
                api_key_id=api_key_id,
                project=project_id,
            )
        )

    return records


def pull(api_key: str, since: datetime, until: datetime | None = None) -> list[UsageRecord]:
    """Fetch and normalize OpenAI usage+cost data from `since` (UTC,
    inclusive) up to `until` (UTC, exclusive; defaults to now)."""
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        usage_rows = _fetch_usage_rows(client, since, until)
        cost_rows = _fetch_cost_rows(client, since, until)
    return _allocate_cost(usage_rows, cost_rows)
