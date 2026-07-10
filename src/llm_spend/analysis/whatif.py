"""Same-model what-if comparisons: batch gap, service-tier gap, cache hit rate.

Hard boundary (see CLAUDE.md): no cross-model repricing. Every function
here only ever compares a model against itself — different token counts
for a different model, or a different provider's pricing, never enter the
math. Different model families use different tokenizers, so "this would
cost less on model X" isn't a valid computation from aggregate usage data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from llm_spend.schema import UsageRecord

# Usage APIs often report a dated snapshot ("gpt-5.4-mini-2026-03-17",
# "claude-sonnet-5-20260115") rather than the bare alias pricing.yaml keys
# on — observed against a real OpenAI account, where every real usage row
# came back with a snapshot suffix and silently missed every pricing.yaml
# lookup as a result. Falls back to the alias if the exact snapshot isn't
# priced separately; still same-model (never a different model's rate).
_DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def _resolve_model_pricing(pricing: dict, provider: str, model: str) -> dict | None:
    provider_prices = pricing.get(provider, {})
    if model in provider_prices:
        return provider_prices[model]
    return provider_prices.get(_DATE_SUFFIX_RE.sub("", model))


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
    output_token_share: float  # output_tokens / total_tokens — see SERVICE_TIER_GAP_CAVEAT


@dataclass(frozen=True, slots=True)
class CacheHitRow:
    model: str
    input_tokens: int
    cached_tokens: int
    hit_rate: float


BATCH_GAP_CACHE_CAVEAT = "Cache interactions aren't modeled — the batch estimate prices all input tokens at the full batch rate, so potential savings are understated for models with a meaningful cache hit rate."


def batch_gap(records: list[UsageRecord], pricing: dict) -> list[BatchGapRow]:
    """For real-time (non-batch) usage of models `pricing` has batch rates
    for, estimate what that same token volume would have cost at batch
    rates. This is a heuristic ("potentially batch-able, if the workload
    doesn't need to be real-time") — the report must never present it as a
    guaranteed saving, since only the caller knows if the workload can
    tolerate batch's async turnaround.

    Doesn't model cache economics: `hypothetical_cost` prices every input
    token (including the cached portion) at the full batch_input rate, but
    cache reads were actually billed at a steep discount in `actual_cost`,
    and both OpenAI and Anthropic document cache and batch discounts as
    stacking. That means this systematically understates potential_savings
    for high-cache-hit models (conservative-direction, not an overpromise,
    but still a real gap — see BATCH_GAP_CACHE_CAVEAT, surfaced in the
    report). Not fixed here rather than risk a confidently-wrong number:
    the exact stacking formula isn't verified per-provider against real
    billing data.
    """
    by_model: dict[tuple[str, str], list[UsageRecord]] = {}
    for r in records:
        if r.batch_flag:
            continue
        by_model.setdefault((r.provider, r.model), []).append(r)

    rows = []
    for (provider, model), recs in by_model.items():
        model_pricing = _resolve_model_pricing(pricing, provider, model)
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


SERVICE_TIER_GAP_CAVEAT = (
    "Cost-per-1K blends input and output tokens, which bill at different rates — a tier with "
    "proportionally more output tokens looks pricier here even at identical underlying rates. "
    "Check output_token_share before concluding one tier is actually cheaper."
)


def service_tier_gap(records: list[UsageRecord]) -> dict[str, list[TierRow]]:
    """For each model with more than one service_tier present in the data,
    compare the cost-per-1K-tokens actually realized on each tier. This
    uses real billed cost from the records themselves, not pricing.yaml —
    it's comparing tiers you've already paid for, not projecting a rate for
    one you haven't used.

    Deliberately doesn't split cost_per_1k into separate input/output
    rates: `cost_usd` is a single blended figure per record (that's how
    providers bill it and how the connectors store it), so a true split
    would require estimating one from pricing.yaml — which would mean
    "real billed cost" silently becomes "modeled cost" for this one
    function. `output_token_share` is reported instead: real observed
    data, no pricing assumptions, that lets a reader spot when the
    cost-per-1K gap is really just a workload-mix difference. See
    SERVICE_TIER_GAP_CAVEAT, surfaced in the report.
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
            input_tokens = sum(r.input_tokens for r in recs)
            output_tokens = sum(r.output_tokens for r in recs)
            total_tokens = input_tokens + output_tokens
            total_cost = sum(r.cost_usd for r in recs)
            cost_per_1k = (total_cost / total_tokens * 1000) if total_tokens else 0.0
            output_share = (output_tokens / total_tokens) if total_tokens else 0.0
            rows.append(
                TierRow(
                    service_tier=tier,
                    total_cost=total_cost,
                    total_tokens=total_tokens,
                    cost_per_1k_tokens=cost_per_1k,
                    output_token_share=output_share,
                )
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
