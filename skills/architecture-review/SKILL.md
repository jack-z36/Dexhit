---
name: architecture-review
description: "Review a Codebase Architecture (DOCS/01_知识/ARCHITECTURE.md) for completeness, internal consistency, and real enforceability — not business behavior. Checks that layers, dependency rules, package boundaries, ports/adapters, ownership, invariants, and architecture tests are present, non-contradictory, and that every invariant has a real enforcement mechanism (or an honest 'manual review only'). Use when the user wants to review an architecture before handing off to /to-tickets, asks 'is this architecture complete/enforceable', or after /architecture-design."
---

# Architecture Review

Review an existing `DOCS/01_知识/ARCHITECTURE.md` (produced by `/architecture-design`) along three axes:

1. **Completeness** — every required section exists and is filled with project truth, not placeholders.
2. **Internal consistency** — the layers, dependency DAG, package boundaries, ports/adapters, ownership, and invariants do not contradict each other.
3. **Enforceability** — every invariant has a real mechanical gate or is honestly marked `manual review only`.

This is a **structural** review. It does NOT verify business behavior (the control law, IK residual, safety state machine) — that belongs to `/code-review` and `/tdd`. It does NOT redesign the architecture — gaps go back to `/architecture-design`.

## Inputs

- `DOCS/01_知识/ARCHITECTURE.md` — the thing under review.
- The originating spec — to confirm the System Architecture restatement is faithful (not silently re-scoped).
- `DOCS/01_知识/ADR/` — to confirm the architecture does not contradict accepted decisions, and that hard-to-reverse decisions were routed to ADRs rather than buried in prose.
- `CONTEXT.md` — to confirm terminology matches the glossary.

## Checklist

Run every item; report PASS / FAIL / GAP with the offending location.

### Completeness

- [ ] System Architecture (runtime) and Codebase Architecture (layers) are in **separate** sections and not conflated.
- [ ] Layers present with a single, stated dependency direction.
- [ ] Each layer/package has Owns / May / **Must not**.
- [ ] Dependency DAG rendered (Mermaid), with forbidden edges listed explicitly.
- [ ] Package boundaries map to real language/ROS packages; no `utils/`/`common/` dumping ground.
- [ ] Ports table lists every external dependency with a production adapter and a test/fake adapter sharing one contract.
- [ ] Public interfaces + ownership table present (one fact, one owner).
- [ ] Invariant → enforcement table present.
- [ ] Architecture tests distinguished from behavior tests.
- [ ] Open questions (未知问题) listed, not silently assumed.

### Internal consistency

- [ ] No invariant contradicts the dependency DAG (an invariant "Core MUST NOT import rclpy" must match the DAG's Core node having no runtime edge).
- [ ] No forbidden edge in the DAG is simultaneously allowed by the layer table.
- [ ] Every port named in the adapter table is depended-on only, never depends on an adapter.
- [ ] Ownership table has exactly one owner per fact — no shared ownership of state.
- [ ] Public-interface contracts match the spec's stated message contract (field count, units, empties).
- [ ] Terminology matches `CONTEXT.md`; no invented synonyms.

### Enforceability

- [ ] Every invariant has a gate column filled with a concrete mechanism OR an explicit `manual review only` (no blank, no vague "should be checked").
- [ ] No invariant claims a CI/lint gate that does not actually exist in the repo — if the gate is not implemented yet, mark it `GAP: gate not yet wired` rather than passing it.
- [ ] The invariant → mechanism table's "Status" column honestly distinguishes enforced vs manual.

## Output

A review report (do not edit ARCHITECTURE.md here):

1. **Verdict**: Architecture is complete & enforceable / has gaps / has contradictions.
2. **Fails** (contradictions): list each with location and the conflicting statements.
3. **Gaps** (missing sections or unenforced invariants): list each with what is missing.
4. **Recommended next step**: re-run `/architecture-design` for the flagged items, or (if complete and enforceable) hand off to `/to-tickets` with Spec + ARCHITECTURE.md.

## What this skill must NOT do

- Verify business behavior or run the system (route to `/code-review`, `/tdd`, `/diagnosing-bugs`).
- Redesign the architecture — it reports gaps; `/architecture-design` fixes them.
- Edit ARCHITECTURE.md, the spec, ADRs, or `CONTEXT.md`.
- Block on stylistic preferences — only flag structural/completeness/enforceability issues.
