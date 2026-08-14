#!/usr/bin/env python3
"""Parse a plan/ticket document into a dependency-ordered dispatch plan.

Input: a Markdown plan with ticket sections like:

    ### T01 — `some_package` title
    **Blocked by**：无，可立即开始。
    ...

    ### T05 — title
    **Blocked by**：T01、T02、T03。

Outputs:
  1. ticket list with blockers
  2. DAG validation (acyclic, all blockers exist)
  3. dependency-ordered waves (parallel batches)
  4. potential write-scope overlaps (shared backtick tokens)

This mirrors the frontier-building step of /dispatch-tickets. It is a helper, not
a source of truth: the main agent still confirms conflicts against ARCHITECTURE.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

SECTION_RE = re.compile(r"^###\s+(T\d+)\s*[—\-:]\s*(.*)$")
BLOCKED_RE = re.compile(r"^\*\*Blocked by\*\*\s*[:：]\s*(.*)$")
TOKEN_RE = re.compile(r"`([^`]+)`")


def parse_plan(text: str) -> list[dict]:
    tickets: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if current is not None:
                tickets.append(current)
            current = {"id": m.group(1), "title": m.group(2).strip(), "blocked_by": [], "tokens": []}
            continue
        if current is None:
            continue
        b = BLOCKED_RE.match(line)
        if b:
            raw = b.group(1).strip().rstrip("。.")
            if raw and ("无" not in raw or "立即" in raw):
                # handles "T01、T02、T03" (、-separated) or "T01, T02" (comma)
                ids = [t for t in re.split(r"[、,，\s]+", raw) if re.fullmatch(r"T\d+", t)]
                current["blocked_by"] = ids
            current["tokens"] += TOKEN_RE.findall(line)
        else:
            current["tokens"] += TOKEN_RE.findall(line)
    if current is not None:
        tickets.append(current)
    return tickets


def validate(tickets: list[dict]) -> list[str]:
    errors: list[str] = []
    ids = {t["id"] for t in tickets}
    for t in tickets:
        for b in t["blocked_by"]:
            if b not in ids:
                errors.append(f"{t['id']} blocked by missing ticket {b}")
    # cycle detection via Kahn
    indeg = {t["id"]: len(t["blocked_by"]) for t in tickets}
    edges: dict[str, list[str]] = defaultdict(list)
    for t in tickets:
        for b in t["blocked_by"]:
            edges[b].append(t["id"])
    order: list[str] = []
    q = deque(sorted(i for i, d in indeg.items() if d == 0))
    while q:
        n = q.popleft()
        order.append(n)
        for m in sorted(edges.get(n, [])):
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(order) != len(tickets):
        errors.append("cycle detected in blocking edges; cannot topologically sort")
    return errors


def waves(tickets: list[dict]) -> list[list[str]]:
    by_id = {t["id"]: t for t in tickets}
    remaining = set(by_id)
    result: list[list[str]] = []
    while remaining:
        ready = sorted(i for i in remaining if all(b not in remaining for b in by_id[i]["blocked_by"]))
        if not ready:
            # cycle — should have been caught by validate()
            result.append(sorted(remaining))
            break
        result.append(ready)
        remaining -= set(ready)
    return result


def overlap_hints(tickets: list[dict]) -> list[str]:
    by_id = {t["id"]: t for t in tickets}
    hints: list[str] = []
    for i, a in enumerate(tickets):
        for b in tickets[i + 1:]:
            shared = sorted(set(a["tokens"]) & set(b["tokens"]))
            if shared:
                hints.append(f"{a['id']} ↔ {b['id']}: shared tokens {shared}")
    return hints


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan", help="path to the plan markdown")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    text = Path(args.plan).read_text(encoding="utf-8")
    tickets = parse_plan(text)
    if not tickets:
        print("ERROR: no ticket sections (### T<NN>) found")
        return 1

    print(f"Tickets: {', '.join(t['id'] for t in tickets)}")
    for t in tickets:
        print(f"  {t['id']} blocked by {t['blocked_by'] or 'none'} — {t['title']}")

    errors = validate(tickets)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1

    print("\nDispatch waves (parallel batches, blockers first):")
    for i, w in enumerate(waves(tickets), 1):
        print(f"  wave {i}: {', '.join(w)}")

    hints = overlap_hints(tickets)
    if hints:
        print("\nPotential write-scope overlaps (confirm before parallelizing):")
        for h in hints:
            print(f"  {h}")
    else:
        print("\nNo shared backtick tokens between tickets.")

    print("\nPASS: DAG acyclic, all blockers resolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
