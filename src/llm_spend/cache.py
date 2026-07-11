"""Local JSON cache for pulled usage records.

This is the only place API usage/cost data touches disk. The cache
directory writes its own `.gitignore` (`*`) the first time it's created —
defense in depth for whatever directory `llm-spend pull` gets run in,
independent of this repo's own top-level .gitignore — and every file in it
is written 0600 from creation (opened with that mode directly, rather than
chmod'd after the fact, so there's no window where the file briefly exists
with default/broader permissions).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from llm_spend.schema import UsageRecord, from_json_dict, to_json_dict

DEFAULT_CACHE_DIR = Path(".llm-spend-cache")


def _ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    gitignore = cache_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")


def _write_json_0600(path: Path, data) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)


def write_records(
    provider: str, records: list[UsageRecord], cache_dir: Path = DEFAULT_CACHE_DIR
) -> Path:
    _ensure_cache_dir(cache_dir)
    path = cache_dir / f"{provider}.json"
    _write_json_0600(path, [to_json_dict(r) for r in records])
    return path


def read_records(provider: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> list[UsageRecord]:
    path = cache_dir / f"{provider}.json"
    if not path.exists():
        return []
    return [from_json_dict(d) for d in json.loads(path.read_text())]


def write_reconciliation_total(
    provider: str,
    total_usd: Decimal,
    since: datetime,
    until: datetime | None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    """Stores the independent, ungrouped cost total fetched alongside a
    `pull`, for the report's reconciliation check. Kept separate from the
    per-record cache file since it's a single number, not a list of
    UsageRecord, and each `pull` call fully overwrites the prior one for
    that provider — so this always covers exactly the same window as the
    records cached alongside it. Written as a string, like cost_usd in
    schema.py: json has no Decimal type.
    """
    _ensure_cache_dir(cache_dir)
    path = cache_dir / f"{provider}.reconciliation.json"
    _write_json_0600(
        path,
        {
            "total_usd": str(total_usd),
            "since": since.isoformat(),
            "until": until.isoformat() if until else None,
        },
    )
    return path


def read_reconciliation_total(provider: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Decimal | None:
    path = cache_dir / f"{provider}.reconciliation.json"
    if not path.exists():
        return None
    return Decimal(json.loads(path.read_text())["total_usd"])
