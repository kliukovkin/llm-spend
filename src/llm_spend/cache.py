"""Local JSON cache for pulled usage records.

This is the only place API usage/cost data touches disk. The cache
directory writes its own `.gitignore` (`*`) the first time it's created —
defense in depth for whatever directory `llm-spend pull` gets run in,
independent of this repo's own top-level .gitignore — and every file in it
is written 0600.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from llm_spend.schema import UsageRecord, from_json_dict, to_json_dict

DEFAULT_CACHE_DIR = Path(".llm-spend-cache")


def _ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    gitignore = cache_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")


def write_records(
    provider: str, records: list[UsageRecord], cache_dir: Path = DEFAULT_CACHE_DIR
) -> Path:
    _ensure_cache_dir(cache_dir)
    path = cache_dir / f"{provider}.json"
    path.write_text(json.dumps([to_json_dict(r) for r in records], indent=2))
    os.chmod(path, 0o600)
    return path


def read_records(provider: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> list[UsageRecord]:
    path = cache_dir / f"{provider}.json"
    if not path.exists():
        return []
    return [from_json_dict(d) for d in json.loads(path.read_text())]
