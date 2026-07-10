# llm-spend

Read-only CLI for LLM API spend: attribution, a rough end-of-month forecast,
and same-model what-if comparisons (batch gap, cache hit rate, service-tier
gap). Supports OpenAI and Anthropic.

## Install

```
uv pip install -e .
```

## Usage

```
export OPENAI_ADMIN_KEY=...      # sk-admin-... — Admin API key with api.usage.read + api.costs.read scopes
export ANTHROPIC_ADMIN_KEY=...   # sk-ant-admin01-...

llm-spend pull --provider openai --since 2026-06-01
llm-spend pull --provider anthropic --since 2026-06-01
llm-spend report --format html -o report.html
```

Don't have real usage history yet, or just want to see what the report looks
like? Generate a synthetic dataset instead of pulling from a real account:

```
PYTHONPATH=src python scripts/synth_data.py --scale both --out synthetic/
```

This writes `synthetic/personal.json` and `synthetic/team.json` — copy
either into `.llm-spend-cache/openai.json` (or `anthropic.json`) and run
`llm-spend report` against it.

CSV import (an alternative to admin API keys) isn't implemented yet.

## Security posture

- **Read-only, no proxy.** `llm-spend` never writes to a provider or routes
  any of your real API traffic through it — it only calls the admin
  usage/cost *reporting* endpoints.
- **Least-privilege keys.** Use an Admin API key scoped to read-only
  usage/cost access, not a general-purpose key. OpenAI: create one under
  **Settings → Organization → Admin keys**, not the project-scoped
  **Settings → API keys** page, and grant only the `api.usage.read` /
  `api.costs.read` scopes. Anthropic: create an Admin API key
  (`sk-ant-admin01-...`) under your organization settings.
- **Keys never touch disk.** They're read from `OPENAI_ADMIN_KEY` /
  `ANTHROPIC_ADMIN_KEY` environment variables only — never written to a
  config file or the local cache.
- **What's cached locally:** `.llm-spend-cache/` holds one JSON file per
  provider with the normalized usage/cost data `pull` retrieved — nothing
  else. Files are written `0600`, and the directory writes its own
  `.gitignore` the first time it's created.
- **Nothing leaves your machine** beyond the read calls you configure (or a
  CSV you point it at, once that lands). No telemetry, no analytics, no
  external requests from the report renderer.

## Status

v0.1, under active development.

- `pull --provider openai` and `pull --provider anthropic` work: usage+costs,
  pagination, rate-limit backoff. Verified against a real OpenAI account.
- `report` works against cached data: attribution, forecast, same-model
  what-if (batch gap, tier gap, cache hit rate), overspend scenario, and
  same-weekday anomaly detection, in both terminal and HTML.
- `import` (CSV, no API key needed) is still stubbed.
