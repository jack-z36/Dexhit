---
name: dispatch-tickets
description: "Coordinate parallel execution of a set of implementation tickets by dispatching sub-agents. The main agent builds the dependency frontier, spawns one executor sub-agent per ticket (in parallel when write scopes do not overlap), reviews each result, and iterates up to three rounds. Use when the user has a ticket set or implementation plan (from /to-tickets, a plan doc under DOCS/03_工程/, or GitHub issues) and wants to execute it efficiently in one session rather than one ticket per window/thread. Complements /to-tickets (which creates tickets) and /implement (which does one ticket); does NOT redesign architecture or redefine requirements."
---

# Dispatch Tickets

Execute a ticket set by dispatching **sub-agents** in parallel, instead of opening one thread/window per ticket. The main agent owns dispatch and iteration; executor sub-agents each implement one ticket; reviewer sub-agents check the result.

This skill is the parallelization layer **above** `/implement`. `/to-tickets` creates the tickets; `/dispatch-tickets` runs them; `/code-review` can gate the integrated result.

## Relationship to other skills (do not overlap)

- `/to-tickets` — creates tickets + blocking edges. This skill **consumes** them.
- `/implement` — implements ONE ticket. This skill spawns a sub-agent that effectively does `/implement` for each ticket.
- `/code-review` — reviews the integrated diff after this skill finishes (optional gate).
- `/architecture-design` / `/architecture-review` — upstream; the tickets assume ARCHITECTURE is already fixed. This skill does **not** re-decide layers, boundaries, owners, or invariants.

## Core inputs

1. **Ticket set** — one of:
   - a plan doc under `DOCS/03_工程/` with `### T<NN>` sections and `**Blocked by**` edges (current project state), or
   - one file per ticket under `DOCS/03_工程/<feature>/issues/`, or
   - GitHub issues (fetch via `gh issue list`/`gh issue view`, see `DOCS/02_约束/编程执行/issue-tracker.md`).
2. **Spec** — `DOCS/03_工程/<feature>/...Spec.md` or the spec issue.
3. **ARCHITECTURE.md** — `DOCS/01_知识/ARCHITECTURE.md` (layers, package layout, dependency DAG, invariants A01–A22, Ports/Adapters, ownership).
4. **Domain + decisions** — `CONTEXT.md` (root) and `DOCS/01_知识/ADR/`.

## Sub-agent tool inventory (exact Codex tools)

| Tool | Role |
| --- | --- |
| `multi_agent_v1__spawn_agent` | spawn an executor or reviewer sub-agent |
| `multi_agent_v1__wait_agent` | wait for one or more sub-agents to finish |
| `multi_agent_v1__send_input` | send review feedback to an executor (`interrupt=true`) |
| `multi_agent_v1__close_agent` | close a finished sub-agent |
| `multi_agent_v1__resume_agent` | resume a closed sub-agent to reuse its context |

Spawning guidance: pass `fork_context=false` so an executor starts with only the prompt (lean context) rather than the whole thread; put everything it needs in `message`. Omit `model`/`reasoning_effort` to inherit the parent model.

## Main agent workflow

### 1. Load context

Read `AGENTS.md`, then `DOCS/02_约束/编程执行/编程执行规则.md` (§2 context-loading order). Then read the ticket set, the Spec, `ARCHITECTURE.md`, `CONTEXT.md`, and relevant ADRs. Do not load all of DOCS into sub-agents — only the slice each ticket needs.

### 2. Parse and validate the ticket DAG

For a plan doc, run:

```bash
python skills/dispatch-tickets/scripts/dispatch_plan.py DOCS/03_工程/<plan>.md
```

It validates the DAG (acyclic, every blocker exists) and prints dependency-ordered **waves** plus **potential write-scope overlaps**. For GitHub-issue or per-file ticket sets, build the same DAG manually from each ticket's blocking edges.

### 3. Build the frontier

The frontier is every ticket whose blockers are all complete or explicitly waived. Dispatch in waves: within a wave, tickets are independent (no blocking edge between them).

### 4. Spawn executor sub-agents in parallel — conflict-aware

Spawn one executor per frontier ticket. **Never spawn two executors in parallel whose write scopes overlap** (same package, same file, same module, same config key, same hardware path). The script's overlap hints are a starting point; confirm against `ARCHITECTURE.md`'s package layout before spawning.

Give each executor exactly one ticket and the minimal context: the ticket, the Spec sections it needs, the relevant ARCHITECTURE invariants, and the relevant ADR. See [references/subagent-roles.md](./references/subagent-roles.md) for the executor prompt template.

### 5. Wait, review, iterate

Use `multi_agent_v1__wait_agent` with a long timeout (minutes) on the wave's executors. When an executor finishes, review its reported changes against its ticket:

- **PASS** — changes satisfy the ticket's acceptance criteria and don't violate any ARCHITECTURE invariant or ADR. Integrate the changes; mark the ticket done; close the agent.
- **FAIL / unclear** — send concrete feedback via `multi_agent_v1__send_input` (`interrupt=true`) to the same agent. Up to **three** execute-review rounds total per ticket. On the third failure, stop and escalate to the user (report the blocker, do not loop).

Use a **reviewer sub-agent** (read-only, see references) when the ticket is large or the result is ambiguous — it reads the ticket, the diff, and the ARCHITECTURE invariants, and returns one verdict with concrete fix requests. Reviewers may run in parallel; they must not write the same feedback file.

### 6. Recompute and continue

After each wave passes, recompute the frontier (new tickets unblock). Continue until every ticket is complete or explicitly blocked.

### 7. Finish

Report per-ticket status (done / blocked / failed), the integrated changed files, and which tickets remain. Do **not** commit — Git commits require explicit user authorization (编程执行规则 §13). Point at `/code-review` for the integrated gate if the user wants it.

## Executor sub-agent contract

Each executor, given one ticket, must:

- Read only its ticket and the context listed in its prompt (not unrelated tickets or the whole plan).
- Validate the ticket's `Blocked by` are all done before editing (report if not).
- Respect ARCHITECTURE's layers, dependency DAG, package boundaries, Ports/Adapters, ownership, and invariants. A change that violates an invariant is a fail.
- Implement only that ticket; run its local validation (TDD, `colcon test`, import checks); record the command and result.
- Report: changed file paths, validation commands, results, unverified items, and any invariant it was unsure about.
- **Never** edit dispatch indexes, other tickets, or shared architecture/ADR files; **never** run Git sync or commit.

## Reviewer sub-agent contract

A reviewer is read-only and must:

- Read the ticket, the reported diff, and the relevant ARCHITECTURE invariants/ADRs.
- Return exactly one verdict: `PASS` / `FAIL` / `BLOCKED_ENV` / `BLOCKED_HARDWARE_EXPECTED`, plus concrete fix requests on FAIL.
- Never edit source, tests, tickets, architecture, or Git state.
- Never claim a hardware-dependent behavior passed without hardware.

## Conflict rules (must hold)

Do not parallelize two executors when their write scopes overlap in any of: package, file, module, config key, or hardware path. Reviewers are read-only and may parallelize, but must not write the same feedback file.

## Stop conditions (stop and report, do not keep going)

- Ticket set, plan, or issue references disagree with each other.
- The DAG has a cycle or references a missing ticket.
- A ticket's blocker is not complete and not explicitly waived.
- A ticket is `blocked` / `waiting_user`.
- Three execute-review rounds fail for the same ticket.
- A hardware ticket claims success without hardware, or lacks a hardware-blocked condition.

## What this skill must NOT do

- Redefine requirements (route to `/to-spec`) or re-grill the plan (route to `/grill-with-docs`).
- Redesign architecture (route to `/architecture-design` / `/architecture-review`).
- Re-slice tickets (that is `/to-tickets`; this skill consumes its output).
- Commit or push — sub-agents and the main agent both leave Git to the user per 编程执行规则 §13.
- Spawn sub-agents for trivial single-file edits that are faster done inline.
- Replace `/implement` entirely — this skill still delegates to one-ticket implementation work, just in parallel.
