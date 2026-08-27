"""Read-only topic health and business readiness for Launchpad.

The monitor deliberately has no ROS dependency.  A ROS adapter (or a test)
injects the topic name, message and a monotonic receive time through
``observe``.  This keeps the status semantics testable without pretending
that a synthetic message is evidence of a live ROS graph or hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

RAW_HAND = "/rokoko/{side}/raw_hand"
RETARGETING_STATE = "/hand_retargeting/{side}/state"
CONTROL_STATE = "/o10_control/{side}/state"
PROVIDER_JOINT_STATES = "/o10/{side}/joint_states"

GREEN = "green"
YELLOW = "yellow"
RED = "red"


@dataclass
class _TopicProbe:
    expected_hz: float
    timeout_factor: float
    last_seen: float | None = None
    first_seen: float | None = None
    count: int = 0

    def observe(self, now: float) -> None:
        if self.first_seen is None:
            self.first_seen = now
        self.last_seen = now
        self.count += 1

    def snapshot(self, now: float) -> dict[str, Any]:
        age = None if self.last_seen is None else max(0.0, now - self.last_seen)
        timeout = self.timeout_factor / self.expected_hz
        if self.count > 1 and self.first_seen is not None and now > self.first_seen:
            frequency = (self.count - 1) / (self.last_seen - self.first_seen)
        else:
            frequency = 0.0
        return {
            "alive": age is not None and age <= timeout + 1e-9,
            "age_sec": age,
            "frequency_hz": round(frequency, 3),
            "expected_hz": self.expected_hz,
            "timeout_sec": timeout,
            "samples": self.count,
        }


@dataclass
class _SideState:
    message: Any = None
    probe: _TopicProbe | None = None


def _field(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


class StatusMonitor:
    """Compute the four Launchpad lights from injected observable messages."""

    _KINDS = ("receiver", "retargeting", "control", "provider")
    _TOPIC_KIND = {
        "receiver": RAW_HAND,
        "retargeting": RETARGETING_STATE,
        "control": CONTROL_STATE,
        "provider": PROVIDER_JOINT_STATES,
    }

    def __init__(
        self,
        *,
        sides: tuple[str, ...] = ("left", "right"),
        expected_hz: Mapping[str, float] | None = None,
        timeout_factor: float = 3.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.sides = tuple(sides)
        self._clock = clock
        rates = {kind: 30.0 for kind in self._KINDS}
        if expected_hz:
            rates.update(expected_hz)
        self._states: dict[str, dict[str, _SideState]] = {
            kind: {
                side: _SideState(
                    probe=_TopicProbe(rates[kind], timeout_factor)
                )
                for side in self.sides
            }
            for kind in self._KINDS
        }

    def observe(self, topic: str, message: Any, *, now: float | None = None) -> None:
        """Record one received message at an injected monotonic time."""
        if now is None:
            if self._clock is None:
                raise ValueError("observe requires now or an injected clock")
            now = self._clock()
        for kind, template in self._TOPIC_KIND.items():
            for side in self.sides:
                if topic == template.format(side=side):
                    state = self._states[kind][side]
                    state.message = message
                    assert state.probe is not None
                    state.probe.observe(float(now))
                    return

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        """Return a JSON-safe snapshot suitable for HTTP or WebSocket output."""
        if now is None:
            if self._clock is None:
                raise ValueError("snapshot requires now or an injected clock")
            now = self._clock()
        nodes: dict[str, Any] = {}
        for kind in self._KINDS:
            per_side = {
                side: self._side_snapshot(kind, side, float(now)) for side in self.sides
            }
            statuses = {value["status"] for value in per_side.values()}
            aggregate = RED if RED in statuses else YELLOW if YELLOW in statuses else GREEN
            nodes[kind] = {"status": aggregate, "sides": per_side}
        return {"rate_hz": 5.0, "timestamp": float(now), "nodes": nodes}

    def _side_snapshot(self, kind: str, side: str, now: float) -> dict[str, Any]:
        state = self._states[kind][side]
        assert state.probe is not None
        topic = state.probe.snapshot(now)
        if not topic["alive"]:
            status, reason = RED, "topic_timeout"
            ready = False
        else:
            ready, reason = self._business_ready(kind, state.message)
            status = GREEN if ready else YELLOW
        return {
            "status": status,
            "business_ready": ready,
            "reason": reason,
            "topic": self._TOPIC_KIND[kind].format(side=side),
            **topic,
        }

    @staticmethod
    def _business_ready(kind: str, message: Any) -> tuple[bool, str]:
        if message is None:
            return False, "no_business_message"
        if kind in ("receiver", "provider"):
            return True, "flowing"
        if kind == "retargeting":
            phase = _field(message, "phase")
            tracking = phase in (3, "TRACKING", "tracking")
            published = bool(_field(message, "command_published", False))
            if tracking and published:
                return True, "tracking_and_command_published"
            if phase in (1, "COLLECTING_LENGTHS", "collecting_lengths"):
                return False, "collecting_lengths"
            return False, "not_tracking_or_command_not_published"
        fault = bool(_field(message, "fault_latched", False))
        mask = _field(message, "fault_reason_mask", 0) or 0
        try:
            fault = fault or int(mask) != 0
        except (TypeError, ValueError):
            fault = True
        return (True, "no_fault") if not fault else (False, "fault_latched")
