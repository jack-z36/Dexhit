"""Black-box API tests for the Launchpad stand-in seam."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from typing import Any

from rokoko_omnihand_launchpad import orchestrator as orchestrator_module
from rokoko_omnihand_launchpad.app import create_app
from rokoko_omnihand_launchpad.process_lifecycle import TeardownResult


async def request(app: Any, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload or {}).encode()
    messages: list[dict[str, Any]] = []
    consumed = False

    async def receive() -> dict[str, Any]:
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app({"type": "http", "http_version": "1.1", "method": method, "path": path,
               "raw_path": path.encode(), "query_string": b"", "headers": [(b"content-type", b"application/json")],
               "scheme": "http", "server": ("test", 80), "client": ("test", 1), "root_path": ""}, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return int(start["status"]), json.loads(raw)


def test_validation_rules_and_conditional_preflight():
    app = create_app()
    status, result = asyncio.run(request(app, "POST", "/api/validate", {"blocks": ["hcan_provider", "sim_provider"]}))
    assert status == 200 and not result["valid"]
    status, result = asyncio.run(request(app, "POST", "/api/validate", {"blocks": ["synthetic_input", "hcan_provider"]}))
    assert status == 200 and not result["valid"] and result["confirmations"]
    status, result = asyncio.run(request(app, "POST", "/api/validate", {"blocks": ["synthetic_input", "hcan_provider"], "confirmation": True}))
    assert status == 200 and result["valid"] and result["warnings"]
    status, result = asyncio.run(request(app, "POST", "/api/preflight", {"blocks": ["sim_provider"], "side": "left"}))
    assert status == 200 and "usb_canfd" not in result["required"] and "sim_provider_available" in result["required"]


def test_start_stop_restart_and_crash_are_visible_via_api():
    app = create_app()
    payload = {"blocks": ["rokoko_receiver", "hand_retargeting", "omnihand_o10_control", "sim_provider"],
               "side": "right", "standins": {"sim_provider": {"crash_after": 0.1}}}
    asyncio.run(request(app, "POST", "/api/config", payload))
    _, started = asyncio.run(request(app, "POST", "/api/start"))
    assert started["config"]["side"] == "right"
    assert all(started["nodes"][name]["expected"] for name in payload["blocks"])
    assert started["nodes"]["sim_provider"]["pid"] is not None
    time.sleep(0.2)
    _, crashed = asyncio.run(request(app, "GET", "/api/state"))
    assert crashed["nodes"]["sim_provider"]["actual"] == "crashed"
    assert "not restarted" in crashed["nodes"]["sim_provider"]["alert"]
    _, stopped = asyncio.run(request(app, "POST", "/api/stop"))
    assert all(not node["expected"] for node in stopped["nodes"].values())


def test_single_node_stop_reports_downstream_impact_and_parent_death_is_configured():
    app = create_app()
    asyncio.run(request(app, "POST", "/api/config", {"blocks": ["rokoko_receiver", "hand_retargeting", "omnihand_o10_control"]}))
    _, result = asyncio.run(request(app, "POST", "/api/nodes/rokoko_receiver/start"))
    assert result["pid"]
    _, stopped = asyncio.run(request(app, "POST", "/api/nodes/rokoko_receiver/stop"))
    assert "hand_retargeting" in stopped["downstream_impact"]
    app.state.orchestrator.close()


def test_managed_cleanup_failure_on_node_start_is_http_409_and_unknown_is_404(monkeypatch, tmp_path):
    app = create_app(run_root=tmp_path)
    cleanup_failure = lambda *_args, **_kwargs: TeardownResult("cleanup_failed", (987654,), None)
    try:
        asyncio.run(request(app, "POST", "/api/config", {
            "blocks": ["sim_provider"], "execution_mode": "stub"
        }))
        _, started = asyncio.run(request(app, "POST", "/api/nodes/sim_provider/start"))
        monkeypatch.setattr(orchestrator_module, "stop_process_group", cleanup_failure)
        _, stopped = asyncio.run(request(app, "POST", "/api/nodes/sim_provider/stop"))
        assert stopped["state"]["actual"] == "cleanup_failed"

        status, result = asyncio.run(request(app, "POST", "/api/nodes/sim_provider/start"))
        assert status == 409
        assert "cleanup failed" in result["detail"]

        status, result = asyncio.run(request(app, "POST", "/api/nodes/not-a-block/start"))
        assert status == 404
        assert "unknown block" in result["detail"]
    finally:
        monkeypatch.undo()
        app.state.orchestrator.close()


def test_start_with_empty_block_selection_is_rejected_409(tmp_path):
    app = create_app(run_root=tmp_path)
    try:
        asyncio.run(request(app, "POST", "/api/config", {"blocks": [], "execution_mode": "stub"}))
        status, result = asyncio.run(request(app, "POST", "/api/start"))
        assert status == 409
        assert "no blocks selected" in result["detail"]
    finally:
        app.state.orchestrator.close()


def test_snapshot_validation_respects_saved_confirmation(tmp_path):
    app = create_app(run_root=tmp_path)
    try:
        danger = {"blocks": ["rokoko_receiver", "synthetic_input", "hcan_provider"],
                  "execution_mode": "stub", "confirmation": True}
        _, configured = asyncio.run(request(app, "POST", "/api/config", danger))
        assert configured["validation"]["valid"] is True
        _, state = asyncio.run(request(app, "GET", "/api/state"))
        assert state["config"]["blocks"] == danger["blocks"]
        assert state["validation"]["valid"] is True
        assert state["validation"]["confirmations"] and not state["validation"]["errors"]
    finally:
        app.state.orchestrator.close()
