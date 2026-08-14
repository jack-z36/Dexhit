---
name: architecture-design
description: "Map an existing Spec and current codebase into a Codebase Architecture: layers, responsibilities, dependency rules, package boundaries, ports/adapters, public interfaces, ownership, architecture invariants, and mechanically-enforceable architecture tests. Produces DOCS/01_知识/ARCHITECTURE.md. Use when the user has a spec and wants to design the codebase architecture before implementation, asks for an architecture/layering/dependency design, or says 'design the architecture'. Does NOT redefine product requirements, write implementation code, or create implementation tickets."
---

# Architecture Design

Turn an existing Spec into a **Codebase Architecture**: an explicit, mechanically-checkable statement of how the codebase is layered, what each layer owns, which way dependencies may flow, where package boundaries sit, and how the outside world (hardware, SDK, ROS runtime) is isolated behind ports.

This skill does **not** redefine requirements (that is `/to-spec`), improve a single module's interface (that is `/codebase-design`), or start implementation (that is `/implement`). It owns the *whole-codebase* structural map.

## Inputs (read first, do not guess)

1. The originating Spec — usually under `DOCS/03_工程/<feature>/` or an issue (see `DOCS/02_约束/编程执行/issue-tracker.md`).
2. Current codebase state — `git log`, existing `src/<stage>/` packages, the four-stage main chain (`collection → raw MCAP → processing → LeRobotDataset v3 → training → ACT bundle → deployment`).
3. Domain language — `CONTEXT.md` at the repo root; use its exact terms.
4. Existing decisions — `DOCS/01_知识/ADR/` (read ADRs in the area; never re-litigate them).
5. Module facts — `DOCS/01_知识/` knowledge pages (e.g. the O10 control contract).

## Output

Write a single `DOCS/01_知识/ARCHITECTURE.md` (architecture is stable knowledge; per 文档维护规则 §1 it does NOT go at the repo root). Use [templates/ARCHITECTURE.md](./templates/ARCHITECTURE.md) as the scaffold. Register it in `DOCS/01_知识/INDEX.md`. Architecture decisions that are hard-to-reverse and surprising become ADRs under `DOCS/01_知识/ADR/` via `/domain-modeling` — do not duplicate them in ARCHITECTURE.md, link them.

## Distinguish two architectures explicitly

A common failure is conflating these. ARCHITECTURE.md must keep them in separate sections:

**A. System Architecture (runtime data flow)** — what the spec already states. For this project that is the live ROS graph: `rokoko_bridge_node → hand_retargeting_node → O10 control entry → omnihand_2025_node → physical O10`. This is *input*, restated for context. Do not redesign it here.

**B. Codebase Architecture (compile/dependency structure)** — what this skill produces: the layering, package boundaries, and dependency DAG the *code* must obey. Example for this domain:

```
ROS Runtime / framework glue        ← knows about rclpy, nodes, topics
        ↓ (depends on)
Application / Orchestration         ← node lifecycle, state machines, wiring
        ↓
Core / Domain                       ← IK math, control law, safety predicates
        ↓
Types / Contracts                   ← message types, value objects, pure data

Control Core ──→ HardwarePort (interface) ←──┐
                                              │ same public contract
HardwareAdapter (prod) ──────────────────────┤
SoftwareAdapter (test/fake) ──────────────────┘
```

## Process

### 1. Re-state the System Architecture from the spec

Pull the runtime module chain and the per-module responsibilities ("Owns / Must not") straight from the spec and the relevant `01_知识` page. This anchors everything. Mark anything the spec leaves open as **未知问题** (per 用户概念体系 §6), never as a silent assumption.

### 2. Choose layers for THIS domain

Do not paste a generic `UI → Service → Repo` stack. Derive layers from the real runtime/compile seam. For a ROS 2 control project the natural axis is *framework-knowledge → pure*. Read [references/architecture-patterns.md](./references/architecture-patterns.md) for the Clean / Hexagonal / DDD vocabulary adapted to robotics, then decide the layer set. State the dependency direction once, up front (almost always: outer depends on inner; Core depends on nothing framework-specific).

### 3. Responsibilities per layer/package

For each layer and each package, write the Owns / May / **Must not** triple. The "Must not" lines are the seed of invariants — be concrete. Prefer ROS package boundaries (`src/<stage>/<pkg>/`) over invented module folders; do not create a `utils/` or `common/` dumping ground.

### 4. Dependency rules as a DAG

Write explicit allowed/forbidden edges and render the result as a dependency DAG (Mermaid `flowchart`). Forbid, by name: cycles, core→runtime imports, business logic→vendor SDK, production code importing test/fake adapters. Every forbidden edge becomes a candidate invariant.

### 5. Ports / Adapters / Providers

Enumerate every external dependency (hardware, vendor SDK, filesystem, clock, network, model assets, ROS runtime, CAN/USB). Decide which must sit behind a Port (interface) with a production Adapter and a test/fake Adapter sharing the same public contract. This is where domain knowledge matters: here, the control core reaches hardware only through a HardwarePort, and the vendor `omnihand_2025_node` is an external adapter, not owned code.

### 6. Public interfaces & ownership

List the stable public interfaces (ROS topics/services with their message contract, plus any pure-Python APIs). For each important type/state/config, name a single owner ("who owns this"). One fact, one owner — no two modules own the same state.

### 7. Architecture invariants

Distill §3–§6 into short, checkable invariants written as MUST/MUST NOT. Each must be derived from the real architecture, not copied from examples. Example shape (adapt to reality): *Core MUST NOT import rclpy*; *Control code MUST NOT import the vendor SDK directly*; *SoftwareAdapter and HardwareAdapter MUST implement the same Port*.

### 8. Mechanical enforcement — the critical step

For every invariant, decide how it is enforced. ARCHITECTURE.md must not be "advice". For each invariant record one of:

- a concrete mechanism: import lint (e.g. a `check_imports.py` gate), a dependency-rule test, a structural/architecture test (pytest that asserts the package graph is acyclic and legal), a CI gate, a compile-time boundary;
- or **`manual review only`** — and say so explicitly. Never pretend an unenforced invariant is guaranteed.

Map `Invariant → mechanism → test/lint/CI gate`. See [references/enforcement.md](./references/enforcement.md) for patterns.

### 9. Architecture tests vs behavior tests

State explicitly which tests verify *structure* (the code did not "grow crooked": no illegal imports, no dependency inversion, no prod→fake coupling, package graph acyclic) versus which verify *behavior* (the control law, IK residual, safety state machine). Architecture tests live next to the package they constrain and are part of the architecture contract.

### 10. Hand off

The architecture is done when `to-tickets` could slice implementation work from it without re-deciding structure. Point `to-tickets` at the Spec **and** ARCHITECTURE.md. Do not write tickets here.

## What this skill must NOT do

- Re-grill product requirements or change the spec (route to `/grill-with-docs` / `/to-spec`).
- Implement code or create tickets (route to `/implement` / `/to-tickets`).
- Own ADRs or the glossary — surface decisions and route them to `/domain-modeling` + `DOCS/01_知识/ADR/`.
- Redesign a single module's depth — that is `/codebase-design`. This skill is whole-system.
- Assume a generic web stack. Derive layers from the real ROS/robotics domain.
- Write `ARCHITECTURE.md` to the repo root — it goes in `DOCS/01_知识/` per the harness.
