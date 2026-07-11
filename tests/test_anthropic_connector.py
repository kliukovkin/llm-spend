from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from llm_spend.connectors import anthropic as anthropic_connector

_RealClient = httpx.Client  # captured before any test monkeypatches httpx.Client

BUCKET_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
BUCKET_START_STR = "2026-06-01T00:00:00Z"
BUCKET_END_STR = "2026-06-02T00:00:00Z"


def _usage_page(results, has_more=False, next_page=None):
    return {
        "data": [{"starting_at": BUCKET_START_STR, "ending_at": BUCKET_END_STR, "results": results}],
        "has_more": has_more,
        "next_page": next_page,
    }


def _usage_result(**overrides):
    result = {
        "account_id": None,
        "api_key_id": "apikey_a",
        "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
        "cache_read_input_tokens": 100,
        "context_window": None,
        "inference_geo": None,
        "model": "claude-sonnet-5",
        "output_tokens": 200,
        "server_tool_use": {"web_search_requests": 0},
        "service_account_id": None,
        "service_tier": "standard",
        "uncached_input_tokens": 900,
        "workspace_id": "wrkspc_a",
    }
    result.update(overrides)
    return result


def _cost_page(results, has_more=False, next_page=None):
    return {
        "data": [{"starting_at": BUCKET_START_STR, "ending_at": BUCKET_END_STR, "results": results}],
        "has_more": has_more,
        "next_page": next_page,
    }


def _cost_result(amount_cents, **overrides):
    result = {
        "amount": str(amount_cents),
        "context_window": None,
        "cost_type": "tokens",
        "currency": "USD",
        "description": "Claude Sonnet 5 Usage - Input Tokens",
        "inference_geo": None,
        "model": "claude-sonnet-5",
        "service_tier": "standard",
        "token_type": "uncached_input_tokens",
        "workspace_id": "wrkspc_a",
    }
    result.update(overrides)
    return result


def _client_for(handler) -> httpx.Client:
    return _RealClient(
        base_url=anthropic_connector.BASE_URL,
        headers={"x-api-key": "test-key", "anthropic-version": anthropic_connector.ANTHROPIC_VERSION},
        transport=httpx.MockTransport(handler),
    )


def test_pull_joins_usage_and_cost_single_key(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page([_usage_result()]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page([_cost_result(150.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    record = records[0]
    assert record.provider == "anthropic"
    assert record.model == "claude-sonnet-5"
    assert record.api_key_id == "apikey_a"
    assert record.project == "wrkspc_a"
    assert record.input_tokens == 1000  # 900 uncached + 100 cache-read
    assert record.output_tokens == 200
    assert record.cached_tokens == 100  # cache reads only, not cache-creation writes
    assert record.cost_usd == pytest.approx(1.5)  # 150 cents -> $1.50
    assert record.batch_flag is False


def test_cache_creation_counts_toward_input_but_not_cached_tokens(monkeypatch):
    usage_result = _usage_result(
        uncached_input_tokens=500,
        cache_read_input_tokens=0,
        cache_creation={"ephemeral_1h_input_tokens": 300, "ephemeral_5m_input_tokens": 200},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page([usage_result]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page([_cost_result(100.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    assert records[0].input_tokens == 1000  # 500 + 300 + 200
    assert records[0].cached_tokens == 0  # cache writes aren't cache hits


def test_pull_splits_cost_across_token_types_for_same_model(monkeypatch):
    # Cost Report breaks one model's cost into up to 5 token_type rows.
    cost_results = [
        _cost_result(100.0, token_type="uncached_input_tokens"),
        _cost_result(10.0, token_type="cache_read_input_tokens"),
        _cost_result(5.0, token_type="cache_creation.ephemeral_5m_input_tokens"),
        _cost_result(50.0, token_type="output_tokens"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page([_usage_result()]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page(cost_results))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    assert records[0].cost_usd == Decimal("1.65")  # (100+10+5+50)/100


def test_pull_splits_cost_proportionally_across_api_keys(monkeypatch):
    usage_results = [
        _usage_result(api_key_id="apikey_a", uncached_input_tokens=800, output_tokens=200, cache_read_input_tokens=0),
        _usage_result(api_key_id="apikey_b", uncached_input_tokens=200, output_tokens=800, cache_read_input_tokens=0),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page(usage_results))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page([_cost_result(200.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 2
    total_cost = sum(r.cost_usd for r in records)
    assert total_cost == pytest.approx(2.0)
    by_key = {r.api_key_id: r for r in records}
    assert by_key["apikey_a"].cost_usd == pytest.approx(1.0)
    assert by_key["apikey_b"].cost_usd == pytest.approx(1.0)


def test_batch_service_tier_sets_batch_flag(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page([_usage_result(service_tier="batch")]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page([_cost_result(50.0, service_tier="batch")]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    assert records[0].batch_flag is True
    assert records[0].service_tier == "batch"


def test_non_token_cost_becomes_tagged_other_record(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page([]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(
                200,
                json=_cost_page(
                    [
                        _cost_result(
                            75.0,
                            cost_type="web_search",
                            model=None,
                            token_type=None,
                            description="Web Search Usage",
                        )
                    ]
                ),
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    assert records[0].model == "other:web_search"
    assert records[0].input_tokens == 0
    assert records[0].cost_usd == pytest.approx(0.75)
    assert records[0].project == "wrkspc_a"


def test_orphan_token_cost_bucket_becomes_other_model_record(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(200, json=_usage_page([]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page([_cost_result(325.0, model="claude-opus-4-8")]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert len(records) == 1
    assert records[0].model == "claude-opus-4-8"
    assert records[0].input_tokens == 0
    assert records[0].cost_usd == pytest.approx(3.25)


def test_pull_paginates_usage_results(monkeypatch):
    page_one = _usage_page([_usage_result(api_key_id="apikey_a")], has_more=True, next_page="cursor1")
    page_two = _usage_page([_usage_result(api_key_id="apikey_b", workspace_id="wrkspc_b")], has_more=False)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            calls.append(request.url.params.get("page"))
            if request.url.params.get("page") is None:
                return httpx.Response(200, json=page_one)
            return httpx.Response(200, json=page_two)
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(
                200,
                json=_cost_page(
                    [_cost_result(100.0), _cost_result(100.0, workspace_id="wrkspc_b")]
                ),
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert calls == [None, "cursor1"]
    assert {r.api_key_id for r in records} == {"apikey_a", "apikey_b"}


def test_pull_retries_on_429_then_succeeds(monkeypatch):
    attempts = {"usage": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            attempts["usage"] += 1
            if attempts["usage"] == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, text="rate limited")
            return httpx.Response(200, json=_usage_page([_usage_result()]))
        if request.url.path == "/v1/organizations/cost_report":
            return httpx.Response(200, json=_cost_page([_cost_result(100.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    records = anthropic_connector.pull("test-key", since=BUCKET_START)

    assert attempts["usage"] == 2
    assert len(records) == 1


def test_pull_raises_on_non_retryable_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/usage_report/messages":
            return httpx.Response(401, text="invalid api key")
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    with pytest.raises(anthropic_connector.AnthropicAdminAPIError, match="401"):
        anthropic_connector.pull("test-key", since=BUCKET_START)


def test_fetch_reconciliation_total_sums_ungrouped_costs(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/cost_report":
            assert "group_by" not in request.url.params
            return httpx.Response(200, json=_cost_page([_cost_result(1050.0), _cost_result(525.0)]))
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    total = anthropic_connector.fetch_reconciliation_total("test-key", since=BUCKET_START)
    assert total == pytest.approx(15.75)  # (1050+525)/100


def test_fetch_reconciliation_total_paginates(monkeypatch):
    page_one = _cost_page([_cost_result(1000.0)], has_more=True, next_page="cursor1")
    page_two = _cost_page([_cost_result(500.0)], has_more=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/cost_report":
            if request.url.params.get("page") is None:
                return httpx.Response(200, json=page_one)
            return httpx.Response(200, json=page_two)
        raise AssertionError(f"unexpected path {request.url.path}")

    monkeypatch.setattr(anthropic_connector.httpx, "Client", lambda **kwargs: _client_for(handler))
    total = anthropic_connector.fetch_reconciliation_total("test-key", since=BUCKET_START)
    assert total == pytest.approx(15.0)  # (1000+500)/100
