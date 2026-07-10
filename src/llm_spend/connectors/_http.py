"""Shared HTTP helpers for provider admin API connectors.

Both OpenAI's and Anthropic's usage/cost endpoints use the same
has_more/next_page/page cursor convention and the same retry-on-429/5xx
semantics, so this logic is factored out rather than duplicated per
connector.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator

import httpx

MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Caps a hostile or buggy Retry-After value (some servers also send an
# HTTP-date instead of a seconds count, which isn't a float at all) — fine
# to wait a while for a one-shot CLI pull, not fine to sleep for hours.
MAX_RETRY_AFTER_SECONDS = 60.0
JITTER_SECONDS = 0.5


def get_with_backoff(
    client: httpx.Client, path: str, params: dict, error_cls: type[Exception]
) -> dict:
    for attempt in range(MAX_RETRIES):
        response = client.get(path, params=params)
        if response.status_code in RETRYABLE_STATUS:
            if attempt == MAX_RETRIES - 1:
                raise error_cls(
                    f"{path} failed after {MAX_RETRIES} attempts: {response.status_code} {response.text}"
                )
            retry_after = response.headers.get("retry-after")
            try:
                delay = min(float(retry_after), MAX_RETRY_AFTER_SECONDS) if retry_after else 2**attempt
            except ValueError:
                delay = 2**attempt  # not a plain seconds count (e.g. an HTTP-date) — fall back
            time.sleep(delay + random.uniform(0, JITTER_SECONDS))
            continue
        if response.status_code >= 400:
            raise error_cls(f"{path} returned {response.status_code}: {response.text}")
        return response.json()
    raise error_cls(f"exhausted retries for {path}")  # unreachable, keeps type-checkers happy


def paginate(client: httpx.Client, path: str, params: dict, error_cls: type[Exception]) -> Iterator[dict]:
    """Yield every time bucket across all pages of a usage/costs endpoint."""
    page_params = dict(params)
    while True:
        payload = get_with_backoff(client, path, page_params, error_cls)
        yield from payload["data"]
        if not payload.get("has_more"):
            return
        page_params = dict(params, page=payload["next_page"])
