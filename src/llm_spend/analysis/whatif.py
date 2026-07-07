"""Same-model what-if comparisons: batch gap, service-tier gap, cache hit rate.

Hard boundary (see CLAUDE.md): no cross-model repricing. Every function
here only ever compares a model against itself — different token counts
for a different model, or a different provider's pricing, never enter the
math. Different model families use different tokenizers, so "this would
cost less on model X" isn't a valid computation from aggregate usage data.
"""

from __future__ import annotations

from dataclasses import dataclass

from llm_spend.schema import UsageRecord


@dataclass(frozen=True, slots=True)
class BatchGapRow:
    provider: str
    model: str
    actual_cost: float
    hypothetical_batch_cost: float
    potential_savings: float


@dataclass(frozen=True, slots=True)
class TierRow:
    service_tier: str
    total_cost: float
    total_tokens: int
    cost_per_1k_tokens: float


@dataclass(frozen=True, slots=True)
class CacheHitRow:
    model: str
    input_tokens: int
    cached_tokens: int
    hit_rate: float


def batch_gap(records: list[UsageRecord], pricing: dict) -> list[BatchGapRow]:
    """For real-time (non-batch) usage of models `pricing` has batch rates
    for, estimate what that same token volume would have cost at batch
    rates. This is a heuristic ("potentially batch-able, if the workload
    doesn't need to be real-time") — the report must never present it as a
    guaranteed saving, since only the caller knows if the workload can
    tolerate batch's async turnaround.
    """
    by_model: dict[tuple[str, str], list[UsageRecord]] = {}
    for r in records:
        if r.batch_flag:
            continue
        by_model.setdefault((r.provider, r.model), []).append(r)

    rows = []
    for (provider, model), recs in by_model.items():
        model_pricing = pricing.get(provider, {}).get(model)
        if not model_pricing or "batch_input" not in model_pricing or "batch_output" not in model_pricing:
            continue
        actual_cost = sum(r.cost_usd for r in recs)
        input_tokens = sum(r.input_tokens for r in recs)
        output_tokens = sum(r.output_tokens for r in recs)
        hypothetical_cost = (
            input_tokens * model_pricing["batch_input"] / 1_000_000
            + output_tokens * model_pricing["batch_output"] / 1_000_000
        )
        rows.append(
            BatchGapRow(
                provider=provider,
                model=model,
                actual_cost=actual_cost,
                hypothetical_batch_cost=hypothetical_cost,
                potential_savings=actual_cost - hypothetical_cost,
            )
        )
    rows.sort(key=lambda row: row.potential_savings, reverse=True)
    return rows


def service_tier_gap(records: list[UsageRecord]) -> dict[str, list[TierRow]]:
    """For each model with more than one service_tier present in the data,
    compare the cost-per-1K-tokens actually realized on each tier. This
    uses real billed cost from the records themselves, not pricing.yaml —
    it's comparing tiers you've already paid for, not projecting a rate for
    one you haven't used.
    """
    by_model: dict[str, dict[str, list[UsageRecord]]] = {}
    for r in records:
        if r.service_tier is None:
            continue
        by_model.setdefault(r.model, {}).setdefault(r.service_tier, []).append(r)

    result: dict[str, list[TierRow]] = {}
    for model, tiers in by_model.items():
        if len(tiers) < 2:
            continue
        rows = []
        for tier, recs in tiers.items():
            total_tokens = sum(r.input_tokens + r.output_tokens for r in recs)
            total_cost = sum(r.cost_usd for r in recs)
            cost_per_1k = (total_cost / total_tokens * 1000) if total_tokens else 0.0
            rows.append(
                TierRow(service_tier=tier, total_cost=total_cost, total_tokens=total_tokens, cost_per_1k_tokens=cost_per_1k)
            )
        rows.sort(key=lambda row: row.cost_per_1k_tokens)
        result[model] = rows
    return result


def cache_hit_rate(records: list[UsageRecord]) -> list[CacheHitRow]:
    """Your actual cache hit rate per model, straight from the data.
    Deliberately doesn't suggest prompt restructuring — that's out of v0.1
    scope; this just reports the number.
    """
    by_model: dict[str, list[UsageRecord]] = {}
    for r in records:
        by_model.setdefault(r.model, []).append(r)

    rows = []
    for model, recs in by_model.items():
        total_input = sum(r.input_tokens for r in recs)
        total_cached = sum(r.cached_tokens for r in recs)
        if total_input == 0:
            continue
        rows.append(
            CacheHitRow(model=model, input_tokens=total_input, cached_tokens=total_cached, hit_rate=total_cached / total_input)
        )
    rows.sort(key=lambda row: row.input_tokens, reverse=True)
    return rows
