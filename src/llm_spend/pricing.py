"""Loader for the model price table (pricing.yaml, versioned in the package).

Used only for same-model what-if math (batch gap, cache-savings estimates)
in analysis/whatif.py — actual spend always comes from the provider's cost
API, never this file. See pricing.yaml's header for sourcing/update notes.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from importlib import resources

import yaml


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    text = resources.files("llm_spend").joinpath("pricing.yaml").read_text()
    raw = yaml.safe_load(text)
    return {
        provider: (
            {model: {rate: Decimal(str(value)) for rate, value in rates.items()} for model, rates in models.items()}
            if provider != "as_of"
            else models
        )
        for provider, models in raw.items()
    }
