---
name: implement
description: Implement a piece of work described by a spec or set of tickets, using TDD at pre-agreed seams, running typechecks and tests regularly, then reporting changes and verification results for review. Use when the user asks to implement work from a spec, ticket, or plan, or says "implement this".
---

Implement the work described by the user in the spec or tickets.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.

Do NOT commit automatically. Once the review is done, report the staged/unstaged changes, the verification results, and the validation commands run. Committing follows 编程执行规则 §13 (Git safety): only commit when the user explicitly authorizes it, and before committing check `git status`, nested repos, secrets, and large/model/data files.
