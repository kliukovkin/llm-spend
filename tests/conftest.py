import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from llm_spend.schema import UsageRecord

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def make_record(**overrides) -> UsageRecord:
    defaults = dict(
        bucket_ts=datetime(2026, 6, 1, tzinfo=timezone.utc),
        provider="openai",
        model="gpt-5.4-mini",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=Decimal("0.01"),
    )
    defaults.update(overrides)
    # Accept plain float/int cost_usd from call sites for convenience;
    # UsageRecord itself requires Decimal.
    if not isinstance(defaults["cost_usd"], Decimal):
        defaults["cost_usd"] = Decimal(str(defaults["cost_usd"]))
    return UsageRecord(**defaults)
