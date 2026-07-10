"""The common shape every connector normalizes usage data into."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

Provider = Literal["openai", "anthropic"]


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One bucket of usage/cost, already attributed to a model and key.

    `cached_tokens` defaults to 0 rather than None: not all provider
    aggregates expose cache hits, and callers should not have to distinguish
    "zero cache hits" from "unknown" until that's confirmed per-connector.
    """

    bucket_ts: datetime
    provider: Provider
    model: str
    input_tokens: int
    output_tokens: int
    # TODO(pre-v0.2): float accumulates summation-order drift (~1e-11 on
    # real datasets) that's harmless for a read-only report but not
    # acceptable once v0.2 pacing/enforcement makes spend decisions on this
    # number. Migrate to Decimal or integer cents before then.
    cost_usd: float
    api_key_id: str | None = None
    project: str | None = None
    service_tier: str | None = None
    batch_flag: bool = False
    cached_tokens: int = 0

    def __post_init__(self) -> None:
        if self.bucket_ts.tzinfo is None:
            raise ValueError("bucket_ts must be timezone-aware (UTC)")
        if self.bucket_ts.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("bucket_ts must be in UTC")
        for field_name in ("input_tokens", "output_tokens", "cached_tokens"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be >= 0")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be >= 0")
        if self.cached_tokens > self.input_tokens:
            raise ValueError("cached_tokens cannot exceed input_tokens")


def to_json_dict(record: UsageRecord) -> dict:
    """JSON-safe representation, used by both the pull cache and synth_data."""
    data = asdict(record)
    data["bucket_ts"] = record.bucket_ts.isoformat()
    return data


def from_json_dict(data: dict) -> UsageRecord:
    data = dict(data)
    data["bucket_ts"] = datetime.fromisoformat(data["bucket_ts"])
    return UsageRecord(**data)
