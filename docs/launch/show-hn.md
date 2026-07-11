<!--
Draft — Georgii edits personally before posting. Placeholders and the
overall narrative arc are intentional starting points, not final copy.
-->

# Show HN draft

**Title:**

> Show HN: llm-spend – see where your OpenAI/Anthropic API money actually goes

**First comment (post as the submitter, top-level):**

> I built this after staring at a bill with no idea which of my keys caused
> it. I run an interactive dev key during the day and a background agent
> that runs unattended overnight and on weekends — the invoice just gives
> you one number. No breakdown by key, no "this was your night agent, not
> you."
>
> llm-spend is a read-only CLI: it pulls usage/cost data from OpenAI's and
> Anthropic's admin APIs (or reads a CSV export if you don't want to grant
> a key at all), and renders a local report — attribution by key/model/
> project, same-model what-if comparisons (batch pricing, cache hit rate),
> and a same-weekday anomaly check.
>
> A few things I cared about getting right:
>
> - The total always comes from the provider's own cost endpoint,
>   cross-checked against an independently-fetched total — if they
>   diverge by more than 1%, the report says so instead of trusting its
>   own arithmetic.
> - Anomaly detection uses leave-one-out z-scores per weekday, not a flat
>   average, so a normal Saturday spike doesn't read as an anomaly.
> - Dollar math is Decimal end to end, not float.
> - Everything stays on your machine — no telemetry, no proxy, nothing
>   sent anywhere except the read calls you configure.
>
> Next up is spend pacing (mid-month: are you on track). Curious what
> breakdown people would actually want first — by key, by day, something
> else entirely?
