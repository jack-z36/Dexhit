---
name: research
description: Investigate a question against high-trust primary sources and capture the findings as a Markdown file in the repo. Use when the user wants a topic researched, docs or API facts gathered, or reading legwork delegated to a background agent.
---

Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Save the findings into the governed `DOCS/` tree (never the repo root), routing by what the findings are:
   - **Research notes, external material, and unsettled intermediate conclusions** → `DOCS/99_learning/` (learning material, non-default context).
   - **Parts already confirmed as stable project facts** → extract into `DOCS/01_知识/`, and clearly mark whether each claim is **当前事实** (verifiable from code/data) or **学习材料** (per 用户概念体系 §6). Don't promote uncertain findings to `01_知识` as if they were confirmed facts.
   Say where you saved it, and register new files in the relevant `INDEX.md` per 文档维护规则 §3.
