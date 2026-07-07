"""Loader for the model price table (pricing.yaml, versioned in the package).

Used only for same-model what-if math (batch gap, cache-savings estimates)
in analysis/whatif.py — actual spend always comes from the provider's cost
API, never this file. See pricing.yaml's header for sourcing/update notes.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    text = resources.files("llm_spend").joinpath("pricing.yaml").read_text()
    return yaml.safe_load(text)
