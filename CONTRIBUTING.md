# Contributing

## Setup

```
uv venv
uv pip install -e . --group dev
```

## Running tests

```
pytest -q
```

Tests use synthetic data (`scripts/synth_data.py`) as the primary fixture
for analysis/report tests — real API calls are exercised manually, not in
CI. If you're touching a connector (`src/llm_spend/connectors/`), mocked
tests should cover the change; a live-account check is a nice-to-have in
the PR description, not a requirement.

## Style

- Type hints everywhere; `dataclasses` for schema, not bare dicts, once
  data crosses a module boundary.
- Connectors own pagination and backoff; callers just get a fully
  materialized list of records — see `src/llm_spend/connectors/_http.py`
  for the shared retry/pagination helpers both providers use.
- `cost_usd` is `Decimal`, never `float` — real per-record costs go below
  a cent, and float summation drifts by summation order.
- See [CLAUDE.md](CLAUDE.md) for the v0.1 scope boundaries (no cross-model
  repricing, forecast is a naive linear trend, anomaly detection needs 21+
  days of history, etc.) before proposing something that crosses one.

## Pull requests

Keep the diff scoped to one change. Add or update tests in the same PR —
this repo has no untested analysis/render code, and PRs that add either
should keep it that way.
