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

### CSV import (no API key)

Don't want to grant an admin key at all? Import a CSV instead. Required
columns: `bucket_ts, provider, model, input_tokens, output_tokens, cost_usd`.
Optional: `api_key_id, project, service_tier, batch_flag, cached_tokens`.
This is llm-spend's own generic schema, not any provider's native export
format — build one from whatever your provider's console gives you, or
write one by hand for a handful of rows.

```
llm-spend import --csv usage_export.csv
llm-spend report
```

### Sharing a report safely

`llm-spend report --share` renders an anonymized version: percentages and
ratios instead of dollar amounts, masked API key/project names ("key-1",
"project-1", ...). Model names stay visible since they're not private
identifiers. Sections with no safe percentage substitute for an absolute
dollar figure (total spend, forecast, overspend scenario, reconciliation)
are dropped entirely — meant to be safe to screenshot into Slack or a
public post.

```
llm-spend report --share
llm-spend report --share --format html -o report_share.html
```

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
  CSV you point it at). No telemetry, no analytics, no external requests
  from the report renderer.

## Status

v0.1, feature-complete for the initial scope described above.

- `pull --provider openai` and `pull --provider anthropic` work: usage+costs,
  pagination, rate-limit backoff, an independent reconciliation total.
  Verified against real OpenAI and Anthropic accounts.
- `import --csv` works: no admin key needed, llm-spend's own generic schema.
- `report` works against cached data (from either `pull` or `import`):
  attribution, forecast, same-model what-if (batch gap, tier gap, cache hit
  rate), overspend scenario, and same-weekday anomaly detection, in both
  terminal and HTML, plus an anonymized `--share` mode for safe screenshots.
