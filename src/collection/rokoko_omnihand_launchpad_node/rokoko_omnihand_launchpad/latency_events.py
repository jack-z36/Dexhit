"""Read-only latency, rate and event views for the Launchpad data-flow page.

This module owns no ROS or O10 business state.  Runtime adapters inject public
messages together with the local receive time; the view keeps the newest
timestamp evidence per side and never invents a timestamp when a field is
absent.  ``events.jsonl`` is read back from the active T07 run so the browser
sees the same append-only event order as the artifact on disk.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


TOPICS = {
    "raw_hand": "/rokoko/{side}/raw_hand",
    "retargeting_state": "/hand_retargeting/{side}/state",
    "command": "/o10_control/{side}/command",
    "control_state": "/o10_control/{side}/state",
    "joint_cmd": "/o10/{side}/joint_cmd",
    "joint_states": "/o10/{side}/joint_states",
}
CHAIN = ("source_timestamp", "receive", "input", "solve", "command", "joint_cmd", "joint_states")


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def stamp(value: Any) -> float | None:
    """Extract a ROS/header-like timestamp, returning None for zero/malformed values."""
    header = _get(value, "header")
    source = _get(value, "stamp") if header is None else _get(header, "stamp")
    if source is None and header is None and _get(value, "sec") is not None:
        source = value
    if source is None:
        return None
    try:
        result = float(_get(source, "sec", 0)) + float(_get(source, "nanosec", 0)) * 1e-9
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result != 0.0 else None


class LatencyEventsStore:
    """Thread-safe injected evidence store used by HTTP and WebSocket views."""

    def __init__(self, *, sides: tuple[str, ...] = ("left", "right"), clock: Callable[[], float] | None = None) -> None:
        self.sides = tuple(sides)
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._latest = {side: {} for side in self.sides}
        self._rates = {side: {kind: [] for kind in TOPICS} for side in self.sides}

    def observe(self, topic: str, message: Any, *, received_at: float | None = None) -> bool:
        now = self._clock() if received_at is None else float(received_at)
        for side in self.sides:
            for kind, template in TOPICS.items():
                if topic != template.format(side=side):
                    continue
                with self._lock:
                    self._latest[side][kind] = {"stamp": stamp(message), "received_at": now, "message": message}
                    samples = self._rates[side][kind]
                    samples.append(now)
                    del samples[:-120]
                return True
        return False

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = self._clock() if now is None else float(now)
        with self._lock:
            sides = {side: self._side_snapshot(side, current) for side in self.sides}
        return {"update_hz": 10.0, "timestamp": current, "sides": sides}

    def _side_snapshot(self, side: str, now: float) -> dict[str, Any]:
        latest = self._latest[side]
        rates: dict[str, Any] = {}
        for kind, values in self._rates[side].items():
            frequency = 0.0
            if len(values) > 1 and values[-1] > values[0]:
                frequency = (len(values) - 1) / (values[-1] - values[0])
            age = None if not values else max(0.0, now - values[-1])
            rates[kind] = {"frequency_hz": round(frequency, 3), "samples": len(values), "age_sec": age}

        evidence: dict[str, float | None] = {name: None for name in CHAIN}
        raw = latest.get("raw_hand", {})
        # Rokoko's source timestamp has unconfirmed epoch/unit.  Preserve it
        # for display, but do not subtract it from local ROS time.
        source = _get(raw.get("message"), "source_timestamp") if raw else None
        evidence["source_timestamp"] = source if isinstance(source, (int, float)) and math.isfinite(float(source)) else None
        evidence["receive"] = raw.get("stamp") if raw else None
        state = latest.get("retargeting_state", {})
        evidence["input"] = stamp(_get(state.get("message"), "input_stamp")) if state else None
        evidence["solve"] = stamp(_get(state.get("message"), "solve_finished_stamp")) if state else None
        evidence["command"] = stamp(latest.get("command", {}).get("message")) if latest.get("command") else None
        evidence["joint_cmd"] = stamp(latest.get("joint_cmd", {}).get("message")) if latest.get("joint_cmd") else None
        evidence["joint_states"] = stamp(latest.get("joint_states", {}).get("message")) if latest.get("joint_states") else None

        hops: list[dict[str, Any]] = []
        for before, after in zip(CHAIN, CHAIN[1:]):
            # source_timestamp is intentionally a different, unverified time
            # domain; showing null is safer than a plausible false latency.
            value = None
            if before != "source_timestamp" and evidence[before] is not None and evidence[after] is not None:
                delta = evidence[after] - evidence[before]
                value = round(delta * 1000.0, 3) if delta >= 0 else None
            hops.append({"from": before, "to": after, "latency_ms": value,
                         "available": value is not None})
        fault = latest.get("control_state", {}).get("message") if latest.get("control_state") else None
        fault_latched = bool(_get(fault, "fault_latched", False)) if fault is not None else None
        mask = _get(fault, "fault_reason_mask", None) if fault is not None else None
        try:
            mask = int(mask) if mask is not None else None
        except (TypeError, ValueError):
            mask = None
        return {"rates": rates, "timestamps": evidence, "hops": hops,
                "fault": {"fault_latched": fault_latched, "fault_reason_mask": mask,
                           "available": fault is not None}}


def read_events(run_path: str | Path | None, *, limit: int = 100) -> list[dict[str, Any]]:
    """Read T07's append-only event artifact without changing its order/source."""
    if not run_path:
        return []
    path = Path(run_path) / "events.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


class RosLatencyEventsAdapter:
    """Subscribe to the public topics needed by :class:`LatencyEventsStore`."""

    def __init__(self, store: LatencyEventsStore) -> None:
        self.store = store
        self._subscriptions: list[Any] = []

    def attach(self, node: Any) -> None:
        from rclpy.qos import QoSProfile
        from rokoko_omnihand_msgs.msg import O10ControlState, RawHandFrame, RetargetingState
        from sensor_msgs.msg import JointState

        qos = QoSProfile(depth=10)
        types = {"raw_hand": RawHandFrame, "retargeting_state": RetargetingState,
                 "command": JointState, "control_state": O10ControlState,
                 "joint_cmd": JointState, "joint_states": JointState}
        for side in self.store.sides:
            for kind, template in TOPICS.items():
                topic = template.format(side=side)
                self._subscriptions.append(node.create_subscription(
                    types[kind], topic,
                    lambda message, selected=topic: self.store.observe(selected, message), qos))
