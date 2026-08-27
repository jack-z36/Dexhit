"""Downsampled, read-only data-flow snapshots for the Launchpad panels.

The store is deliberately fed at a seam: ROS callbacks call :meth:`observe`
with the actual message and receive time, while tests can inject the same
wire-shaped objects without claiming that a ROS graph was running.  No
business state is reconstructed here; the displayed values are copied from
the public JointState and RetargetingState topics.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable


JOINT_TARGET = "/o10_control/{side}/command"
JOINT_FEEDBACK = "/o10/{side}/joint_states"
JOINT_CMD = "/o10/{side}/joint_cmd"
RETARGETING_STATE = "/hand_retargeting/{side}/state"
FINGERS = ("thumb", "index", "middle", "ring", "little")
ACTIVE_JOINT_COUNT = 10


def _get(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stamp(message: Any) -> float | None:
    header = _get(message, "header")
    stamp = _get(header, "stamp")
    if stamp is None:
        return None
    sec = _get(stamp, "sec", 0)
    nanosec = _get(stamp, "nanosec", 0)
    try:
        return float(sec) + float(nanosec) * 1e-9
    except (TypeError, ValueError):
        return None


def _joint_values(message: Any) -> dict[str, float | None]:
    names = list(_get(message, "name", ()) or ())
    positions = list(_get(message, "position", ()) or ())
    values = {str(name): _finite(value) for name, value in zip(names, positions)}
    # A valid O10 sample is exactly ten active positions.  Keep the sample
    # observable even when malformed so the UI can show missing points.
    return {name: values.get(name) for name in names[:ACTIVE_JOINT_COUNT]}


@dataclass
class _Series:
    points: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=120))
    last_received_at: float | None = None

    def append(self, point: dict[str, Any], received_at: float, interval: float) -> None:
        if self.last_received_at is not None and received_at - self.last_received_at < interval:
            return
        self.points.append(point)
        self.last_received_at = received_at


class DataStreamStore:
    """Thread-safe, bounded history for both hand sides."""

    def __init__(
        self,
        *,
        sides: tuple[str, ...] = ("left", "right"),
        sample_hz: float = 10.0,
        history_seconds: float = 12.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if sample_hz <= 0 or history_seconds <= 0:
            raise ValueError("sample_hz and history_seconds must be positive")
        self.sides = tuple(sides)
        self.sample_interval = 1.0 / sample_hz
        capacity = max(2, math.ceil(history_seconds * sample_hz))
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._series: dict[str, dict[str, _Series]] = {
            side: {kind: _Series(deque(maxlen=capacity)) for kind in ("target", "feedback", "joint_cmd", "state")}
            for side in self.sides
        }
        self._latest: dict[str, dict[str, Any]] = {side: {} for side in self.sides}

    def observe(self, topic: str, message: Any, *, received_at: float | None = None) -> bool:
        """Copy one public ROS message into the appropriate downsampled series."""
        now = self._clock() if received_at is None else float(received_at)
        matched = False
        for side in self.sides:
            routes = {
                JOINT_TARGET.format(side=side): "target",
                JOINT_FEEDBACK.format(side=side): "feedback",
                JOINT_CMD.format(side=side): "joint_cmd",
                RETARGETING_STATE.format(side=side): "state",
            }
            kind = routes.get(topic)
            if kind is None:
                continue
            matched = True
            point = self._point(kind, message, now)
            with self._lock:
                self._latest[side][kind] = point
                self._series[side][kind].append(point, now, self.sample_interval)
            break
        return matched

    @staticmethod
    def _point(kind: str, message: Any, received_at: float) -> dict[str, Any]:
        point: dict[str, Any] = {"t": received_at, "stamp": _stamp(message)}
        if kind in ("target", "feedback", "joint_cmd"):
            point["values"] = _joint_values(message)
            point["count"] = len(list(_get(message, "position", ()) or ()))
        else:
            phase = _get(message, "phase")
            ik = list(_get(message, "ik_state", ()) or ())
            residual = list(_get(message, "normalized_residual", ()) or ())
            point.update({
                "phase": int(phase) if isinstance(phase, (int, float)) else phase,
                "ik_state": [int(value) if isinstance(value, (int, float)) else value for value in ik[:5]],
                "normalized_residual": [_finite(value) for value in residual[:5]],
                "residual_available": [bool(value) for value in list(_get(message, "residual_available", ()) or ())[:5]],
            })
        return point

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            sides: dict[str, Any] = {}
            for side in self.sides:
                series = self._series[side]
                joint_names: list[str] = []
                for kind in ("target", "feedback", "joint_cmd"):
                    for name in ((self._latest[side].get(kind) or {}).get("values", {}) or {}):
                        if name not in joint_names and len(joint_names) < ACTIVE_JOINT_COUNT:
                            joint_names.append(name)
                sides[side] = {
                    "sample_hz": round(1.0 / self.sample_interval, 3),
                    "joint_count": ACTIVE_JOINT_COUNT,
                    "joint_names": joint_names,
                    "joints": {kind: list(series[kind].points) for kind in ("target", "feedback", "joint_cmd")},
                    "states": list(series["state"].points),
                    "latest": dict(self._latest[side]),
                }
            return {"sample_hz": round(1.0 / self.sample_interval, 3), "sides": sides}


class RosDataStreamAdapter:
    """Subscribe to the public messages without importing business internals."""

    def __init__(self, store: DataStreamStore, latency_events: Any | None = None) -> None:
        self.store = store
        self.latency_events = latency_events
        self._subscriptions: list[Any] = []

    def attach(self, node: Any) -> None:
        from rclpy.qos import QoSProfile
        from rokoko_omnihand_msgs.msg import RetargetingState
        from sensor_msgs.msg import JointState

        qos = QoSProfile(depth=10)
        for side in self.store.sides:
            for message_type, topic_template in (
                (JointState, JOINT_TARGET),
                (JointState, JOINT_FEEDBACK),
                (JointState, JOINT_CMD),
                (RetargetingState, RETARGETING_STATE),
            ):
                topic = topic_template.format(side=side)
                self._subscriptions.append(
                    node.create_subscription(
                        message_type, topic,
                        lambda message, selected=topic: self._observe(selected, message), qos,
                    )
                )

    def _observe(self, topic: str, message: Any) -> None:
        received_at = self.store._clock()
        self.store.observe(topic, message, received_at=received_at)
        if self.latency_events is not None:
            self.latency_events.observe(topic, message, received_at=received_at)
