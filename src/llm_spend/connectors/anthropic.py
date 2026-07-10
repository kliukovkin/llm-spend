"""Anthropic admin API connector: usage_report/messages + cost_report, joined into UsageRecord.

Requires an organization Admin API key (`sk-ant-admin01-...`), not a
standard key — see https://platform.claude.com/docs/en/manage-claude/admin-api-keys.

Per-user (`account_id`) attribution is a real group_by dimension on the
Usage API and is not gated behind Enterprise — Enterprise orgs use a
separate product (the Claude Enterprise Analytics API, with an Analytics
API key) because Claude Enterprise has no Console/Admin API at all. This
connector targets Console orgs, where per-user data is available; v0.1
doesn't group by it (out of UsageRecord's schema) but it's there if a later
session needs it.

The Cost Report only supports group_by=[workspace_id, description] — no
api_key_id, unlike Usage. Grouping by "description" parses out model/
service_tier/token_type/cost_type per line item (the finest this API gets),
splitting one model's daily cost across up to five token_type rows. We sum
those back into one per-(bucket, workspace, model, service_tier) total, then
allocate it across usage rows sharing that key in proportion to token
volume — same join-and-allocate approach as the OpenAI connector, and for
the same reason: it's a heuristic for the per-key split, but a proportional
split of the same total reconciles exactly against the Cost Report.

Non-token costs (web_search, code_execution, session_usage) have no model
to join against, so each becomes its own record tagged
model="other:<cost_type>" rather than being dropped.

`cached_tokens` counts only cache *reads* (the billing-discounted hits),
not cache *creation* (writes, billed at a premium) — cache writes still
count toward `input_tokens` since they're real tokens sent to the model,
just not toward the "cache hit" figure the whatif/cache-savings analysis
cares about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from llm_spend.connectors import _http
from llm_spend.schema import UsageRecord

BASE_URL = "https://api.anthropic.com/v1"
USAGE_PATH = "/organizations/usage_report/messages"
COSTS_PATH = "/organizations/cost_report"
ANTHROPIC_VERSION = "2023-06-01"

USAGE_GROUP_BY = ["workspace_id", "api_key_id", "model", "service_tier"]
COSTS_GROUP_BY = ["workspace_id", "description"]

# bucket_width=1d caps at 31 buckets for both endpoints (cost_report only
# supports 1d). Pagination (via has_more/next_page) covers longer ranges.
USAGE_MAX_LIMIT = 31
COSTS_MAX_LIMIT = 31


class AnthropicAdminAPIError(RuntimeError):
    """Raised when the Anthropic admin API returns a non-retryable error, or
    retries are exhausted on a retryable one."""


@dataclass(frozen=True, slots=True)
class _UsageRow:
    bucket_start: datetime
    workspace_id: str | None
    api_key_id: str | None
    model: str | None
    service_tier: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int


@dataclass(frozen=True, slots=True)
class _CostRow:
    bucket_start: datetime
    workspace_id: str | None
    model: str | None  # None for non-token cost_types
    service_tier: str | None
    cost_type: str
    amount_usd: float


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_bucket_start(bucket: dict) -> datetime:
    return datetime.fromisoformat(bucket["starting_at"].replace("Z", "+00:00"))


def _time_range_params(since: datetime, until: datetime | None, max_limit: int) -> dict:
    params: dict = {
        "starting_at": _rfc3339(since),
        "bucket_width": "1d",
        "limit": max_limit,
    }
    if until is not None:
        params["ending_at"] = _rfc3339(until)
    return params


def _fetch_usage_rows(client: httpx.Client, since: datetime, until: datetime | None) -> list[_UsageRow]:
    params = _time_range_params(since, until, USAGE_MAX_LIMIT)
    params["group_by"] = USAGE_GROUP_BY
    rows = []
    for bucket in _http.paginate(client, USAGE_PATH, params, AnthropicAdminAPIError):
        bucket_start = _parse_bucket_start(bucket)
        for result in bucket["results"]:
            cache_creation = result.get("cache_creation") or {}
            cache_creation_tokens = cache_creation.get("ephemeral_1h_input_tokens", 0) + cache_creation.get(
                "ephemeral_5m_input_tokens", 0
            )
            cache_read_tokens = result.get("cache_read_input_tokens", 0)
            uncached_tokens = result.get("uncached_input_tokens", 0)
            rows.append(
                _UsageRow(
                    bucket_start=bucket_start,
                    workspace_id=result.get("workspace_id"),
                    api_key_id=result.get("api_key_id"),
                    model=result.get("model"),
                    service_tier=result.get("service_tier"),
                    input_tokens=uncached_tokens + cache_read_tokens + cache_creation_tokens,
                    output_tokens=result.get("output_tokens", 0),
                    cached_tokens=cache_read_tokens,
                )
            )
    return rows


def _fetch_cost_rows(client: httpx.Client, since: datetime, until: datetime | None) -> list[_CostRow]:
    params = _time_range_params(since, until, COSTS_MAX_LIMIT)
    params["group_by"] = COSTS_GROUP_BY
    rows = []
    for bucket in _http.paginate(client, COSTS_PATH, params, AnthropicAdminAPIError):
        bucket_start = _parse_bucket_start(bucket)
        for result in bucket["results"]:
            rows.append(
                _CostRow(
                    bucket_start=bucket_start,
                    workspace_id=result.get("workspace_id"),
                    model=result.get("model"),
                    service_tier=result.get("service_tier"),
                    cost_type=result.get("cost_type") or "tokens",
                    # amount is documented as a decimal string in the
                    # lowest currency unit (cents), e.g. "123.45" -> $1.2345:
                    # https://platform.claude.com/docs/en/api/admin-api/usage-cost/get-cost-report
                    # ("amount: Cost amount in lowest currency units (e.g.
                    # cents) as a decimal string.") NOT YET LIVE-VERIFIED —
                    # no Anthropic admin key was available this session to
                    # confirm against a real pull the way the OpenAI
                    # `amount.value` string-vs-number bug was caught. If a
                    # real Anthropic total looks ~100x off, check here
                    # first before anything else.
                    amount_usd=float(result["amount"]) / 100,
                )
            )
    return rows


def _usage_join_key(row: _UsageRow) -> tuple:
    return (row.bucket_start, row.workspace_id, row.model, row.service_tier)


def _allocate_cost(usage_rows: list[_UsageRow], cost_rows: list[_CostRow]) -> list[UsageRecord]:
    token_cost_by_key: dict[tuple, float] = {}
    other_cost_by_key: dict[tuple, float] = {}
    for row in cost_rows:
        if row.cost_type == "tokens" and row.model is not None:
            key = (row.bucket_start, row.workspace_id, row.model, row.service_tier)
            token_cost_by_key[key] = token_cost_by_key.get(key, 0.0) + row.amount_usd
        else:
            other_key = (row.bucket_start, row.workspace_id, row.cost_type)
            other_cost_by_key[other_key] = other_cost_by_key.get(other_key, 0.0) + row.amount_usd

    usage_by_key: dict[tuple, list[_UsageRow]] = {}
    for row in usage_rows:
        usage_by_key.setdefault(_usage_join_key(row), []).append(row)

    records = []
    for key, rows in usage_by_key.items():
        total_cost = token_cost_by_key.get(key, 0.0)
        total_tokens = sum(r.input_tokens + r.output_tokens for r in rows) or 1
        for row in rows:
            share = (row.input_tokens + row.output_tokens) / total_tokens
            records.append(
                UsageRecord(
                    bucket_ts=row.bucket_start,
                    provider="anthropic",
                    model=row.model or "unknown",
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    cost_usd=round(total_cost * share, 6),
                    api_key_id=row.api_key_id,
                    project=row.workspace_id,
                    service_tier=row.service_tier,
                    batch_flag=(row.service_tier == "batch"),
                    cached_tokens=row.cached_tokens,
                )
            )

    for key, total_cost in token_cost_by_key.items():
        if key in usage_by_key:
            continue
        bucket_start, workspace_id, model, service_tier = key
        records.append(
            UsageRecord(
                bucket_ts=bucket_start,
                provider="anthropic",
                model=model or "other",
                input_tokens=0,
                output_tokens=0,
                cost_usd=round(total_cost, 6),
                project=workspace_id,
                service_tier=service_tier,
                batch_flag=(service_tier == "batch"),
            )
        )

    for (bucket_start, workspace_id, cost_type), total_cost in other_cost_by_key.items():
        records.append(
            UsageRecord(
                bucket_ts=bucket_start,
                provider="anthropic",
                model=f"other:{cost_type}",
                input_tokens=0,
                output_tokens=0,
                cost_usd=round(total_cost, 6),
                project=workspace_id,
            )
        )

    return records


def pull(api_key: str, since: datetime, until: datetime | None = None) -> list[UsageRecord]:
    """Fetch and normalize Anthropic usage+cost data from `since` (UTC,
    inclusive) up to `until` (UTC, exclusive; defaults to now)."""
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        usage_rows = _fetch_usage_rows(client, since, until)
        cost_rows = _fetch_cost_rows(client, since, until)
    return _allocate_cost(usage_rows, cost_rows)


def fetch_reconciliation_total(api_key: str, since: datetime, until: datetime | None = None) -> float:
    """Independent cross-check total for the report's reconciliation flag:
    sums the Cost Report with no group_by at all, over the same range
    `pull` would cover. Deliberately doesn't reuse `_fetch_cost_rows`/
    `_allocate_cost` — those are the same cost rows `pull`'s own total is
    built from, so comparing pull's total against itself can only ever
    match by construction. This is a second, independent read.
    """
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    params = _time_range_params(since, until, COSTS_MAX_LIMIT)
    total = 0.0
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        for bucket in _http.paginate(client, COSTS_PATH, params, AnthropicAdminAPIError):
            for result in bucket["results"]:
                total += float(result["amount"]) / 100
    return total
