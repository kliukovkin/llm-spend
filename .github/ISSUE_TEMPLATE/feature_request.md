---
name: Feature request
about: Suggest an idea for llm-spend
title: ""
labels: enhancement
---

**What problem are you trying to solve?**

Describe the situation, not just the feature — e.g. "I can't tell which
project is driving this month's spike" rather than "add a filter flag".

**What would you want llm-spend to do?**


**Is this in scope?**

Worth a skim of the v0.1 boundaries in [CLAUDE.md](../../CLAUDE.md) first —
in particular, llm-spend won't do cross-model cost repricing ("this would
have cost less on model X"), since different tokenizers make that math
invalid from aggregate usage data alone.
