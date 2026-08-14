# Mechanical Enforcement

Reference for `/architecture-design` step 8. For every invariant, choose a mechanism from the strongest available downward. Never claim an invariant is enforced when it is not — mark unenforceable ones `manual review only`.

## Table of contents

1. Enforcement strength ladder
2. Import-boundary checks
3. Dependency-rule / DAG tests
4. Architecture (structural) tests
5. CI gates
6. The invariant → mechanism table

## 1. Enforcement strength ladder

Prefer the strongest mechanism the project toolchain supports:

1. **Compile / type boundary** — strongest (the code does not load if violated). For Python this is limited; for typed interfaces a `Protocol` + type check helps.
2. **Import lint gate** — a script that fails CI on a forbidden import. Strong and cheap.
3. **Dependency-rule / graph test** — a pytest that walks packages, builds the import/dependency graph, and asserts rules (acyclic, no Core→Runtime edge).
4. **Architecture (structural) test** — asserts structural facts (every adapter implements its Port; prod package does not import the fake adapter).
5. **CI gate** — wire 2–4 into the CI workflow as a blocking step.
6. **Manual review only** — weakest; must be stated explicitly, with a checklist for the reviewer.

## 2. Import-boundary checks

A small `check_imports.py` (or a ruff/custom linter rule) that asserts forbidden imports. Example rules to encode:

- Files under `core/` MUST NOT import `rclpy` or any `*_msgs/msg/*`.
- Files under `core/` and `application/` MUST NOT import the vendor SDK module.
- Files under `application/` MUST NOT import `adapters/software_adapter` (the test fake).
- Production packages MUST NOT import anything from a `test/` tree.

Run it as a pytest (`test_import_boundaries`) so it is part of the normal test command and CI.

## 3. Dependency-rule / DAG tests

Walk the package tree, derive a directed graph from static imports, and assert:

- The graph is **acyclic** (no import cycle).
- Every edge obeys the allowed-direction table (Runtime→Application→Core→Types; never the reverse).
- Each Port is depended-on only, never depends on an Adapter.

A cycle or an illegal edge fails the test with the offending path printed.

## 4. Architecture (structural) tests

Structural pytest cases that verify the code "did not grow crooked", independent of behavior:

- `HardwareAdapter` and `SoftwareAdapter` both satisfy `HardwarePort` (duck-typed / Protocol `isinstance` or method presence).
- No public type is defined in two packages (single ownership).
- Every ROS topic/service named in ARCHITECTURE.md's public-interface table exists as a declared interface or documented node (keeps the doc honest).
- The message contract values documented (e.g. 10 active joints, `velocity`/`effort` empty) are asserted by a contract test against the real message construction.

## 5. CI gates

Add the import check, the DAG test, and the structural tests to CI as blocking steps. An architecture invariant without a gate is `manual review only` until a gate is added — record that gap honestly.

## 6. The invariant → mechanism table

Every ARCHITECTURE.md must produce a table like this (filled with the real project's invariants). Shape:

| Invariant | Mechanism | Gate |
| --- | --- | --- |
| Core MUST NOT import rclpy | import lint | `test_import_boundaries` (CI) |
| Control MUST NOT import vendor SDK | import lint | `test_import_boundaries` (CI) |
| Package graph MUST be acyclic | DAG test | `test_dependency_graph` (CI) |
| HardwareAdapter & SoftwareAdapter MUST implement HardwarePort | structural test | `test_adapter_contracts` (CI) |
| armed_s owned only by control entry | manual review only | reviewer checklist (ownership, code review) |

The last row is the honest case: some invariants (single ownership of a state flag) cannot be fully mechanized — say so, do not fake a gate.
