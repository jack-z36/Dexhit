<!--
Scaffold produced by /architecture-design. Replace every <...> with project-truth.
Keep System Architecture (runtime) and Codebase Architecture (compile/dependency) as
distinct sections. Register this file in DOCS/01_知识/INDEX.md.
-->
# Codebase Architecture — <system or feature name>

> Status: <当前事实 / 目标设计 / 未知问题 — mark each section per 用户概念体系 §6>
> Originating spec: <path or issue>
> Related ADRs: <links into DOCS/01_知识/ADR/>

## A. System Architecture (runtime data flow)

Restate the runtime module chain from the spec. This is context, not something this skill redesigns.

```text
<input> → <node/module> → <node/module> → <output>
```

| Module | Owns | Must not |
| --- | --- | --- |

## B. Codebase Architecture (layers & dependency structure)

### Layers

State the layer set derived for this domain and the single dependency direction.

```text
<layer> → <layer> → <layer>   (outer depends on inner)
```

| Layer | Owns | May | Must not |
| --- | --- | --- | --- |

### Dependency DAG

```mermaid
flowchart TD
    %% render the allowed dependency graph; mark forbidden edges in a separate list
```

Forbidden edges (each becomes an invariant below):

- `<from> → <to>` : reason

## Package / module boundaries

Prefer real language/ROS package boundaries over invented folders. No `utils/`/`common/` dumping ground.

| Package | Responsibility | Depends on | Owned by stage |
| --- | --- | --- | --- |

## Ports, Adapters & Providers

| External dependency | Port (interface) | Production Adapter | Test/Fake Adapter |
| --- | --- | --- | --- |

## Public interfaces & ownership

| Interface (topic/service/api) | Contract (message, fields, units) | Owner |
| --- | --- | --- |

Ownership table (one fact, one owner):

| State / type / config | Single owner |
| --- | --- |

## Architecture invariants → enforcement

| Invariant (MUST / MUST NOT) | Mechanism | Gate | Status |
| --- | --- | --- | --- |

Unenforceable invariants are marked `manual review only` with a reviewer checklist — never fake a gate.

## Architecture tests vs behavior tests

- **Architecture / structural tests** (verify the code did not grow crooked): <list>
- **Behavior tests** (verify the control law / IK / safety): <list — owned by /tdd, referenced here, not duplicated>

## Open questions

Anything the spec left open (未知问题) that this architecture cannot close without a decision. Route hard-to-reverse decisions to `/domain-modeling` + `DOCS/01_知识/ADR/`.
