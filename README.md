# llm-spend

Read-only CLI for LLM API spend: attribution, a rough end-of-month forecast,
and same-model what-if comparisons (batch gap, cache hit rate, service-tier
gap). Supports OpenAI and Anthropic.

## What leaves your machine

Nothing. `llm-spend` only makes read calls to the admin/usage APIs you
configure (or reads a CSV you point it at). No proxying, no writes to any
provider, no telemetry. Everything it produces — the local cache and the
rendered report — stays on disk.

## Install

```
uv pip install -e .
```

## Usage

```
export OPENAI_ADMIN_KEY=...
export ANTHROPIC_ADMIN_KEY=...

llm-spend pull --provider openai --since 2026-06-01
llm-spend pull --provider anthropic --since 2026-06-01
llm-spend report --format html -o report.html
```

Or, without API keys:

```
llm-spend import --csv usage_export.csv
llm-spend report
```

## Status

v0.1, under active development.

- `pull --provider openai` and `pull --provider anthropic` work: usage+costs,
  pagination, rate-limit backoff.
- `report` works against cached data: attribution, forecast, same-model
  what-if (batch gap, tier gap, cache hit rate), overspend scenario, and
  same-weekday anomaly detection, in both terminal and HTML.
- `import` (CSV, no API key needed) is still stubbed.
