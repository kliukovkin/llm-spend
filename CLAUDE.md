# llm-spend

## What this is

A read-only CLI that reports on LLM API spend (OpenAI, Anthropic; more
providers later). It pulls usage/cost data via each provider's admin API (or
imports a CSV export), normalizes it into a common schema, and renders a
local report (terminal + self-contained HTML). No proxy, no writes to any
provider, nothing sent anywhere except the read calls the user configures.

## v0.1 scope and hard boundaries

- **No cross-model cost repricing.** Different model families use different
  tokenizers, so "this would have cost less on model X" is not a valid
  computation from aggregate usage data. What-if comparisons are **same-model
  only**: batch vs. real-time gap, service-tier gap, cache hit-rate savings.
- **Forecast is a naive linear trend to end of month**, always rendered with
  an explicit "rough estimate" disclaimer. No seasonality modeling in v0.1.
- **Cost totals come only from each provider's cost/usage-report endpoint**,
  never computed from `pricing.yaml`. `pricing.yaml` exists solely to power
  same-model what-if math. If a report's total and the provider's own
  dashboard disagree, that's a bug — the report should flag any reconciliation
  gap greater than 1%, and all timestamp bucketing is UTC.
- **Anomaly detection compares against the same weekday**, not a flat
  historical average. Below 21 days of history, the report says so plainly
  instead of computing a z-score on insufficient data.
- **Batch-savings language is always a heuristic** ("potentially
  batch-able if this doesn't need to be real-time"), never stated as fact.
- **Keys only via environment variables** (`OPENAI_ADMIN_KEY`,
  `ANTHROPIC_ADMIN_KEY`) — never written to config files or the local cache.
- **No database.** Everything is local files (JSON cache, YAML config,
  rendered HTML). Cache directories are 0600 and gitignored.

## Stack

- Python 3.12+
- `typer` for the CLI, `rich` for terminal rendering
- `httpx` for API calls (connectors handle pagination and rate-limit backoff)
- `pytest` for tests
- No async framework, no ORM, no web server

## Structure

```
src/llm_spend/
  cli.py            # typer app: pull, import, report
  schema.py         # UsageRecord — the common shape everything normalizes to
  pricing.py        # loads pricing.yaml; same-model what-if math only
  pricing.yaml      # versioned, manually-updated model price table (ships with the package)
  connectors/
    openai.py        # organization usage/completions + costs endpoints
    anthropic.py      # usage_report/messages + cost_report endpoints
    csv_import.py      # normalizes CSV exports into UsageRecord
  analysis/
    attribution.py    # breakdowns by key/model/project, period-over-period movement
    forecast.py       # linear trend + disclaimer
    whatif.py         # same-model only: batch gap, tier gap, cache hit rate
    risk.py           # overspend scenario framing, simple z-score anomalies
  report/
    render.py         # terminal (rich) + one self-contained HTML file
scripts/
  synth_data.py        # synthetic dataset generator (two scales, injected anomalies)
tests/
```

## Commands

```
llm-spend pull --provider openai --since 2026-06-01
llm-spend pull --provider anthropic --since 2026-06-01
llm-spend import --csv usage_export.csv
llm-spend report
llm-spend report --format html -o report.html
```

## Style

- Type hints everywhere; prefer `dataclasses` or `pydantic` for schema, not
  bare dicts, once data crosses a module boundary.
- Connectors own pagination and backoff; callers just get a fully materialized
  list of records.
- Tests from the first commit. Synthetic data (`scripts/synth_data.py`) is the
  primary fixture for analysis/report tests — real API calls are exercised
  manually, not in CI.
