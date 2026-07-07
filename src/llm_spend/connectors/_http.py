"""Shared HTTP helpers for provider admin API connectors.

Both OpenAI's and Anthropic's usage/cost endpoints use the same
has_more/next_page/page cursor convention and the same retry-on-429/5xx
semantics, so this logic is factored out rather than duplicated per
connector.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx

MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


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
            delay = float(retry_after) if retry_after else 2**attempt
            time.sleep(delay)
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
