import httpx
import pytest

from llm_spend.connectors import _http


class _TestError(RuntimeError):
    pass


def _client_for(handler) -> httpx.Client:
    return httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(handler))


def test_get_with_backoff_caps_a_huge_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_http.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(_http.random, "uniform", lambda a, b: 0.0)  # deterministic jitter for the assertion

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "999999"})
        return httpx.Response(200, json={"ok": True})

    with _client_for(handler) as client:
        result = _http.get_with_backoff(client, "/x", {}, _TestError)

    assert result == {"ok": True}
    assert sleeps == [_http.MAX_RETRY_AFTER_SECONDS]


def test_get_with_backoff_falls_back_on_non_numeric_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_http.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(_http.random, "uniform", lambda a, b: 0.0)

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            # Retry-After may legally be an HTTP-date, not a seconds count.
            return httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        return httpx.Response(200, json={"ok": True})

    with _client_for(handler) as client:
        result = _http.get_with_backoff(client, "/x", {}, _TestError)

    assert result == {"ok": True}
    assert sleeps == [2**0]  # falls back to exponential backoff (attempt 0)


def test_get_with_backoff_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _client_for(handler) as client, pytest.raises(_TestError, match="failed after"):
        _http.get_with_backoff(client, "/x", {}, _TestError)
