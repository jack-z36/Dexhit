# Architecture Patterns (robotics-adapted)

Reference for `/architecture-design` step 2 (choosing layers). Read when deciding the layer set and port/adapter boundaries. These are patterns, not a prescription — pick the ones the real domain needs.

## Table of contents

1. Clean Architecture
2. Hexagonal / Ports & Adapters
3. Domain-Driven Design (light)
4. Mapping to a ROS 2 control project
5. Anti-patterns to forbid

## 1. Clean Architecture

The dependency rule: dependencies point inward only. An outer ring may know about an inner ring; an inner ring knows nothing about outer rings.

- **Core / Domain** — pure math, control law, safety predicates, value objects. No framework imports. For Dexhit this is the IK solver, the slew-limit control law, the `motionEnabled` predicate.
- **Application / Orchestration** — node lifecycle, state machines, wiring core to ports. Knows the domain; does not know hardware specifics.
- **Interface Adapters / Runtime** — ROS subscribers, publishers, services, parameter glue. Translates between ROS messages and domain types.
- **Frameworks & external** — rclpy, vendor SDK, hardware drivers. The outermost ring.

Test signal of correct layering: the control law and IK math run in a plain Python unit test with no rclpy, no node, no hardware.

## 2. Hexagonal / Ports & Adapters

- **Port** — an abstract interface (Python `abc`/`Protocol`) that defines how the core talks to the outside world. Driving port = how the outside drives the core; driven port = how the core uses an external capability.
- **Adapter** — a concrete implementation of a port.
- **The core depends on the Port, never on an Adapter.** Adapters are injected.

Robotics mapping: hardware is the classic driven port.

```
Control Core (domain)
   │  depends only on the Port interface
   ▼
HardwarePort  (Protocol: read_active_joints, send_command, read_errors, ...)
   ▲                          ▲
   │ implements               │ implements
HardwareAdapter (prod)        SoftwareAdapter (test/fake)
  └─ wraps vendor SDK           └─ pure Python, simulates feedback/errors
```

Benefit: tests exercise the real control core against `SoftwareAdapter` with no hardware, no CAN, no vendor library. This is exactly the "无真机端到端测试链" the spec demands.

## 3. Domain-Driven Design (light)

- **Ubiquitous language** — every term in code matches `CONTEXT.md` and the spec. Do not invent synonyms.
- **Bounded context / package boundary** — each stage (`collection`, `processing`, `training`, `deployment`) is a natural boundary. Within a stage, one module owns one responsibility.
- **Value objects** — immutable, identified by attributes. A `JointTarget(side, q[10], stamp)` is a value object; a `JointState` ROS message is its wire form.
- **Aggregates / ownership** — only one module owns a given piece of state (e.g. the control entry owns `armed_s`, the retargeting node owns per-finger scale).

## 4. Mapping to a ROS 2 control project (Dexhit)

Suggested layer set — confirm against the real spec each time, do not hardcode:

| Layer | Knows about | Example content | Must not |
| --- | --- | --- | --- |
| Types / Contracts | nothing | `.msg`/`.srv` definitions, pure dataclasses, value objects | import rclpy, any logic |
| Core / Domain | Types only | IK math, slew-limit law, `motionEnabled` predicate, range/finite checks | import rclpy, vendor SDK, ROS messages at runtime |
| Application | Core + Ports | node logic, state machines, armed/fault latches, retargeting pipeline | import vendor SDK directly; reach hardware without a Port |
| Ports | nothing (interfaces) | `HardwarePort` Protocol, `ClockProvider`, `ModelAssetProvider` | contain logic |
| Adapters / Runtime | Application + ports + rclpy/SDK | `HardwareAdapter` (vendor node), `SoftwareAdapter` (fake), ROS node glue | be imported by Core or Application |
| Vendor / external | (not owned) | `omnihand_2025_node`, SDK `.so` | be treated as owned code |

Dependency direction: Runtime/Adapters → Application → Core → Types. Ports are depended-upon, never depending. Vendor sits outside and behind an adapter.

## 5. Anti-patterns to forbid (seed the invariants)

- Core importing `rclpy`, `std_msgs`, or any `rclpy`-typed message at runtime.
- Control code importing the vendor SDK directly instead of through `HardwarePort`.
- A production package importing the test/fake adapter.
- Two modules mutating the same state (e.g. retargeting node and control node both owning `armed_s`).
- A `utils.py` / `common/` package that everything imports (a dependency sink that defeats layering).
- Circular import between Application and Core (Application imports Core is legal; Core importing Application is an inversion).
- Guessing initial hardware state (zero, range midpoint, first upstream target) instead of reading a real feedback frame through the port.
