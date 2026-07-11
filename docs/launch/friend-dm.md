<!--
Draft — Georgii edits personally before sending. Short DM for
founder/indiehacker friends, pitching the CSV path (no admin key needed)
since that's the lowest-trust way for someone who doesn't know you well
yet to try it in a couple minutes.
-->

# Friend DM draft

Hey — I built a small CLI for seeing where your OpenAI/Anthropic spend
actually goes (by key, by model, day-over-day, plus a "does this look
like an anomaly" check). Fully local, read-only, no account needed to try
it.

Fastest way to poke at it without handing over any keys: export a usage
CSV from your provider's dashboard and point llm-spend at it —

```
llm-spend import --csv usage_export.csv
llm-spend report
```

Repo: https://github.com/kliukovkin/llm-spend — would genuinely love a
second pair of eyes before I post this more widely. Anything confusing in
the first five minutes, tell me.
