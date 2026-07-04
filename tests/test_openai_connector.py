from datetime import datetime, timezone

import httpx
import pytest

from llm_spend.connectors import openai as openai_connector

_RealClient = httpx.Client  # captured before any test monkeypatches httpx.Client

BUCKET_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
BUCKET_START_TS = int(BUCKET_START.timestamp())
BUCKET_END_TS = BUCKET_START_TS + 86400


def _usage_page(results, has_more=False, next_page=None):
    return {
        "object": "page",
        "data": [
            {
                "object": "bucket",
                "start_time": BUCKET_START_TS,
                "end_time": BUCKET_END_TS,
                "results": results,
            }
        ],
        "has_more": has_more,
        "next_page": next_page,
    }


def _usage_result(**overrides):
    result = {
        "object": "organization.usage.completions.result",
        "input_tokens": 1000,
        "output_tokens": 200,
        "input_cached_tokens": 100,
        "num_model_requests": 5,
        "project_id": "proj_a",
        "api_key_id": "key_a",
        "model": "gpt-5.4-mini",
        "batch": False,
        "service_tier": "default",
    }
    result.update(overrides)
    return result


def _cost_page(results, has_more=False, next_page=None):
    return {
        "object": "page",
        "data": [
            {
                "object": "bucket",
                "start_time": BUCKET_START_TS,
                "end_time": BUCKET_END_TS,
                "results": results,
            }
        ],
        "has_more": has_more,
        "next_page": next_page,
    }


def _cost_result(amount, **overrides):
    result = {
        "object": "organization.costs.result",
        "amount": {"value": amount, "currency": "usd"},
        "project_id": "proj_a",
        "api_key_id": "key_a",
    }
    result.update(overrides)
    return result


def _client_for(handler) -> httpx.Client:
    return _RealClient(
        base_url=openai_connector.BASE_URL,
        headers={"Authorization": "Bearer test-key"},
        transport=httpx.MockTransport(handler),
    )


def test_pull_joins_usage_and_cost_single_key(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organization/usage/completions":
            return httpx.Response(200, json=_usage_page([_usage_result()]))
        if request.url.path == "/v1/organization/costs":
            return httpx.Response(200, json=_cost_page([_cost_result(1.5)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(openai_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = openai_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    record = records[0]
    assert record.provider == "openai"
    assert record.model == "gpt-5.4-mini"
    assert record.api_key_id == "key_a"
    assert record.project == "proj_a"
    assert record.input_tokens == 1000
    assert record.output_tokens == 200
    assert record.cached_tokens == 100
    assert record.cost_usd == 1.5


def test_pull_splits_cost_proportionally_across_models(monkeypatch):
    usage_results = [
        _usage_result(model="gpt-5.4-mini", input_tokens=800, output_tokens=200),
        _usage_result(model="gpt-5.4", input_tokens=200, output_tokens=800),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organization/usage/completions":
            return httpx.Response(200, json=_usage_page(usage_results))
        if request.url.path == "/v1/organization/costs":
            return httpx.Response(200, json=_cost_page([_cost_result(2.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(openai_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = openai_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 2
    total_cost = sum(r.cost_usd for r in records)
    assert total_cost == pytest.approx(2.0)
    by_model = {r.model: r for r in records}
    # equal total tokens (1000 each) -> equal split
    assert by_model["gpt-5.4-mini"].cost_usd == pytest.approx(1.0)
    assert by_model["gpt-5.4"].cost_usd == pytest.approx(1.0)


def test_pull_paginates_usage_results(monkeypatch):
    page_one = _usage_page([_usage_result(api_key_id="key_a")], has_more=True, next_page="cursor1")
    page_two = _usage_page([_usage_result(api_key_id="key_b", project_id="proj_b")], has_more=False)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organization/usage/completions":
            calls.append(request.url.params.get("page"))
            if request.url.params.get("page") is None:
                return httpx.Response(200, json=page_one)
            return httpx.Response(200, json=page_two)
        if request.url.path == "/v1/organization/costs":
            return httpx.Response(
                200,
                json=_cost_page(
                    [_cost_result(1.0, api_key_id="key_a"), _cost_result(1.0, api_key_id="key_b", project_id="proj_b")]
                ),
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(openai_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = openai_connector.pull("test-key", since=BUCKET_START)

    assert calls == [None, "cursor1"]
    assert {r.api_key_id for r in records} == {"key_a", "key_b"}


def test_pull_retries_on_429_then_succeeds(monkeypatch):
    attempts = {"usage": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organization/usage/completions":
            attempts["usage"] += 1
            if attempts["usage"] == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, text="rate limited")
            return httpx.Response(200, json=_usage_page([_usage_result()]))
        if request.url.path == "/v1/organization/costs":
            return httpx.Response(200, json=_cost_page([_cost_result(1.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(openai_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = openai_connector.pull("test-key", since=BUCKET_START)

    assert attempts["usage"] == 2
    assert len(records) == 1


def test_pull_raises_on_non_retryable_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organization/usage/completions":
            return httpx.Response(401, text="invalid api key")
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(openai_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    with pytest.raises(openai_connector.OpenAIAdminAPIError, match="401"):
        openai_connector.pull("test-key", since=BUCKET_START)


def test_orphan_cost_bucket_becomes_other_record(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organization/usage/completions":
            return httpx.Response(200, json=_usage_page([]))
        if request.url.path == "/v1/organization/costs":
            return httpx.Response(200, json=_cost_page([_cost_result(3.25, api_key_id="key_no_usage")]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(openai_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = openai_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    record = records[0]
    assert record.model == "other"
    assert record.input_tokens == 0
    assert record.output_tokens == 0
    assert record.cost_usd == 3.25
    assert record.api_key_id == "key_no_usage"
