"""OmniHand O10 control: per-side armed/fault-latched hard-slew control.

Layering (ARCHITECTURE A21):
    contracts   -- pure events / effects / enums / config (single source)
    core        -- pure hard slew limiter + soft-target validation
    application -- pure per-side ControlSession aggregate (A03: no ROS imports)
    adapters    -- ROS <-> pure value mapping (the only allowed import site)
    node        -- rclpy wiring: executes effects, feeds confirmations back

The vendor ``omnihand_node`` package is intentionally NOT a dependency.
"""

from __future__ import annotations

__version__ = "0.1.0"