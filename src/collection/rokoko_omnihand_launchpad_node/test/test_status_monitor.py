from __future__ import annotations

import asyncio

from rokoko_omnihand_launchpad.app import create_app
from rokoko_omnihand_launchpad.status_monitor import (
    CONTROL_STATE,
    PROVIDER_JOINT_STATES,
    RAW_HAND,
    RETARGETING_STATE,
    StatusMonitor,
)


def _feed_ready(monitor: StatusMonitor, now: float = 1.0) -> None:
    for side in ("left", "right"):
        monitor.observe(RAW_HAND.format(side=side), {}, now=now)
        monitor.observe(
            RETARGETING_STATE.format(side=side),
            {"phase": "TRACKING", "command_published": True},
            now=now,
        )
        monitor.observe(
            CONTROL_STATE.format(side=side),
            {"fault_latched": False, "fault_reason_mask": 0},
            now=now,
        )
        monitor.observe(PROVIDER_JOINT_STATES.format(side=side), {}, now=now)


def test_ready_messages_produce_green_lights_and_frequency_snapshot():
    monitor = StatusMonitor(sides=("left", "right"))
    _feed_ready(monitor)
    snapshot = monitor.snapshot(now=1.1)

    assert snapshot["rate_hz"] == 5.0
    assert all(node["status"] == "green" for node in snapshot["nodes"].values())
    assert snapshot["nodes"]["retargeting"]["sides"]["left"]["business_ready"] is True


def test_collecting_lengths_is_yellow_but_missing_or_stale_topic_is_red():
    monitor = StatusMonitor(sides=("left",))
    monitor.observe(RAW_HAND.format(side="left"), {}, now=2.0)
    monitor.observe(
        RETARGETING_STATE.format(side="left"),
        {"phase": "COLLECTING_LENGTHS", "command_published": False},
        now=2.0,
    )
    monitor.observe(CONTROL_STATE.format(side="left"), {"fault_latched": False}, now=2.0)
    monitor.observe(PROVIDER_JOINT_STATES.format(side="left"), {}, now=2.0)

    snapshot = monitor.snapshot(now=2.1)
    assert snapshot["nodes"]["retargeting"]["sides"]["left"]["status"] == "yellow"
    assert snapshot["nodes"]["retargeting"]["sides"]["left"]["reason"] == "collecting_lengths"

    stale = monitor.snapshot(now=3.0)
    assert stale["nodes"]["receiver"]["sides"]["left"]["status"] == "red"
    assert stale["nodes"]["provider"]["sides"]["left"]["status"] == "red"


def test_topic_frequency_is_measured_from_injected_receive_times():
    monitor = StatusMonitor(sides=("left",))
    topic = RAW_HAND.format(side="left")
    monitor.observe(topic, {}, now=0.0)
    monitor.observe(topic, {}, now=0.1)
    monitor.observe(topic, {}, now=0.2)

    probe = monitor.snapshot(now=0.2)["nodes"]["receiver"]["sides"]["left"]
    assert probe["frequency_hz"] == 10.0
    assert probe["samples"] == 3


def test_fault_and_missing_business_flag_are_not_green():
    monitor = StatusMonitor(sides=("left",))
    monitor.observe(CONTROL_STATE.format(side="left"), {"fault_latched": True}, now=1.0)
    monitor.observe(RETARGETING_STATE.format(side="left"), {"phase": "TRACKING"}, now=1.0)

    snapshot = monitor.snapshot(now=1.1)
    assert snapshot["nodes"]["control"]["sides"]["left"]["status"] == "yellow"
    assert snapshot["nodes"]["retargeting"]["sides"]["left"]["status"] == "yellow"
    assert snapshot["nodes"]["control"]["sides"]["left"]["reason"] == "fault_latched"


def test_app_state_contains_monitor_snapshot_without_touching_orchestrator():
    app = create_app(clock=lambda: 10.0)
    monitor = app.state.status_monitor
    monitor.observe(RAW_HAND.format(side="left"), {}, now=10.0)

    async def call() -> dict:
        response: list[dict] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            response.append(message)

        await app(
            {"type": "http", "http_version": "1.1", "method": "GET", "path": "/api/state",
             "raw_path": b"/api/state", "query_string": b"", "headers": [],
             "scheme": "http", "server": ("test", 80), "client": ("test", 1), "root_path": ""},
            receive,
            send,
        )
        import json
        return json.loads(b"".join(m.get("body", b"") for m in response if m["type"] == "http.response.body"))

    result = asyncio.run(call())
    assert "status" in result
    assert result["status"]["nodes"]["receiver"]["sides"]["left"]["status"] == "green"
