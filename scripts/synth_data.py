"""Generate synthetic UsageRecord datasets for demos and analysis/report tests.

Two scales, matching the two audiences the report has to be interesting for:
  - personal:  ~$50/month solo developer, one interactive key + one
               overnight background-agent key whose usage concentrates on
               weekends (the "night agent ate N% of the week" story).
  - team:      ~$50K/month, several projects/keys spread across cheap and
               frontier models on both providers, for attribution.

Both scales run >=21 days (the minimum history the anomaly detector needs
before it will compute a same-weekday z-score) and get one injected cost
spike, so analysis code has a real anomaly to find instead of a labeled one.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from llm_spend.schema import UsageRecord, to_json_dict

DAY = timedelta(days=1)


def _daily_records(
    rng: random.Random,
    start: datetime,
    days: int,
    provider: str,
    model: str,
    api_key_id: str,
    project: str,
    base_input_tokens: int,
    base_output_tokens: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
    weekday_multiplier: dict[int, float],
    batch_rate: float,
) -> list[UsageRecord]:
    records = []
    for day_offset in range(days):
        ts = start + day_offset * DAY
        mult = weekday_multiplier.get(ts.weekday(), 1.0) * rng.uniform(0.85, 1.15)
        input_tokens = max(0, round(base_input_tokens * mult))
        output_tokens = max(0, round(base_output_tokens * mult))
        cached_tokens = round(input_tokens * rng.uniform(0.1, 0.4))
        batch_flag = rng.random() < batch_rate
        discount = 0.5 if batch_flag else 1.0
        cost = (
            input_tokens * input_price_per_mtok / 1_000_000
            + output_tokens * output_price_per_mtok / 1_000_000
        ) * discount
        records.append(
            UsageRecord(
                bucket_ts=ts,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=Decimal(str(round(cost, 6))),
                api_key_id=api_key_id,
                project=project,
                service_tier="default",
                batch_flag=batch_flag,
                cached_tokens=cached_tokens,
            )
        )
    return records


def _inject_spike(
    records: list[UsageRecord],
    rng: random.Random,
    start: datetime,
    days: int,
    factor: float,
    min_day: int = 21,
    trailing_buffer: int = 3,
) -> list[UsageRecord]:
    """Multiply one record on one day by `factor`, leaving `min_day` days of
    clean history before it (so a same-weekday comparison has something to
    compare against) and `trailing_buffer` days after it."""
    if days <= min_day + trailing_buffer:
        return records
    day_offset = rng.randrange(min_day, days - trailing_buffer)
    target_date = (start + day_offset * DAY).date()
    candidates = [i for i, r in enumerate(records) if r.bucket_ts.date() == target_date]
    if not candidates:
        return records
    idx = rng.choice(candidates)
    victim = records[idx]
    records[idx] = UsageRecord(
        bucket_ts=victim.bucket_ts,
        provider=victim.provider,
        model=victim.model,
        input_tokens=round(victim.input_tokens * factor),
        output_tokens=round(victim.output_tokens * factor),
        cost_usd=round(victim.cost_usd * Decimal(str(factor)), 6),
        api_key_id=victim.api_key_id,
        project=victim.project,
        service_tier=victim.service_tier,
        batch_flag=victim.batch_flag,
        cached_tokens=victim.cached_tokens,
    )
    return records


def generate_personal(seed: int = 0, days: int = 60, inject_spike: bool = True) -> list[UsageRecord]:
    rng = random.Random(seed)
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    records = []

    # Daytime interactive usage, quiet on weekends.
    records += _daily_records(
        rng, start, days,
        provider="anthropic", model="claude-haiku-4-5",
        api_key_id="key_personal_dev", project="default",
        base_input_tokens=400_000, base_output_tokens=80_000,
        input_price_per_mtok=1.00, output_price_per_mtok=5.00,
        weekday_multiplier={0: 1.1, 1: 1.1, 2: 1.1, 3: 1.1, 4: 1.0, 5: 0.4, 6: 0.3},
        batch_rate=0.0,
    )

    # Overnight background agent, mostly quiet on weeknights, concentrated
    # Fri night through Sunday.
    records += _daily_records(
        rng, start, days,
        provider="openai", model="gpt-5.4-mini",
        api_key_id="key_night_agent", project="default",
        base_input_tokens=250_000, base_output_tokens=60_000,
        input_price_per_mtok=0.75, output_price_per_mtok=4.50,
        weekday_multiplier={0: 0.3, 1: 0.3, 2: 0.3, 3: 0.3, 4: 1.5, 5: 3.5, 6: 3.0},
        batch_rate=0.2,
    )

    records.sort(key=lambda r: r.bucket_ts)
    if inject_spike:
        records = _inject_spike(records, rng, start, days, factor=6.0)
    return records


def generate_team(seed: int = 1, days: int = 60, inject_spike: bool = True) -> list[UsageRecord]:
    rng = random.Random(seed)
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    records = []

    # (provider, model, key, project, base_in, base_out, in_price/mtok, out_price/mtok, batch_rate)
    team_config = [
        ("openai", "gpt-5.4-mini", "key_support_bot", "support", 200_000_000, 40_000_000, 0.75, 4.50, 0.1),
        ("openai", "gpt-5.4", "key_backend_svc", "platform", 80_000_000, 20_000_000, 2.50, 15.00, 0.3),
        ("openai", "gpt-5.5", "key_research", "research", 15_000_000, 6_000_000, 5.00, 30.00, 0.0),
        ("anthropic", "claude-haiku-4-5", "key_support_bot", "support", 150_000_000, 30_000_000, 1.00, 5.00, 0.1),
        ("anthropic", "claude-sonnet-5", "key_product_eng", "platform", 50_000_000, 15_000_000, 2.00, 10.00, 0.2),
        ("anthropic", "claude-opus-4-8", "key_research", "research", 6_000_000, 2_500_000, 5.00, 25.00, 0.0),
    ]

    for provider, model, key, project, base_in, base_out, in_price, out_price, batch_rate in team_config:
        records += _daily_records(
            rng, start, days,
            provider=provider, model=model,
            api_key_id=key, project=project,
            base_input_tokens=base_in, base_output_tokens=base_out,
            input_price_per_mtok=in_price, output_price_per_mtok=out_price,
            weekday_multiplier={0: 1.05, 1: 1.1, 2: 1.1, 3: 1.05, 4: 0.9, 5: 0.4, 6: 0.35},
            batch_rate=batch_rate,
        )

    records.sort(key=lambda r: r.bucket_ts)
    if inject_spike:
        records = _inject_spike(records, rng, start, days, factor=8.0)
    return records


SCALES = {
    "personal": generate_personal,
    "team": generate_team,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic llm-spend usage data")
    parser.add_argument("--scale", choices=[*SCALES, "both"], default="both")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("synthetic"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    scales = SCALES if args.scale == "both" else {args.scale: SCALES[args.scale]}

    for name, generator in scales.items():
        records = generator(seed=args.seed, days=args.days)
        out_path = args.out / f"{name}.json"
        out_path.write_text(json.dumps([to_json_dict(r) for r in records], indent=2))
        total_cost = sum(r.cost_usd for r in records)
        print(f"{name}: {len(records)} records, ${total_cost:,.2f} total over {args.days} days -> {out_path}")


if __name__ == "__main__":
    main()
