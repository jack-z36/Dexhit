# Manual architecture review checklist

These two invariants remain intentionally manual-review-only because static
analysis cannot prove ownership of every runtime state transition:

- [x] A14 — inspect `omnihand_o10_control/node.py`: it only converts ROS
  messages, executes effects, and fills responses; authorization, fault,
  freshness, and limiter state live only in each `ControlSession`.
- [x] A21 — inspect `omnihand_o10_hardware_adapter`, bringup, messages, model,
  and test packages: none owns `armed`, fault, IK, stale, or slew-limit
  business state. Record reviewer, commit/working-tree revision, and evidence
  before production release.

## Review record

- Reviewer: Kepler (`gpt-5.6-luna`), read-only final architecture review.
- Revision: `616e5d2f6ae7fc5cec699f86e00e7811dd5c76e6` plus uncommitted working-tree changes.
- Result: A14 PASS and A21 PASS.
- Evidence: `omnihand_o10_control/node.py`, `omnihand_o10_control/application/control_session.py`,
  `omnihand_o10_hardware_adapter/application/provider.py`, `omnihand_o10_hardware_adapter/backends.py`,
  `rokoko_omnihand_bringup/launch/production.launch.py`, and `rokoko_omnihand_system_test/provider.py`.
- Scope note: this is an architecture ownership review; vendor factory behavior,
  physical feedback semantics, watchdog, and real hardware remain outside this review.
