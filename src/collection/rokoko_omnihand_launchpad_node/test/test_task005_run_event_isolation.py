"""TASK-005 black-box regression tests for run-scoped event snapshots."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from rokoko_omnihand_launchpad.app import create_app
from rokoko_omnihand_launchpad import orchestrator as orchestrator_module
from rokoko_omnihand_launchpad.orchestrator import Orchestrator
from rokoko_omnihand_launchpad.process_lifecycle import TeardownResult

from test_orchestrator_api import request


def _event_types(path: Path) -> list[str]:
    return [json.loads(line)["type"] for line in path.read_text().splitlines()]


def _run_path(response: dict[str, Any]) -> Path:
    return Path(response["run"])


def _wait_for_crash(app: Any) -> dict[str, Any]:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        _, state = asyncio.run(request(app, "GET", "/api/state"))
        if state["nodes"]["sim_provider"]["actual"] == "crashed":
            return state
        time.sleep(0.01)
    raise AssertionError("sim_provider did not reach crashed state")


def _events_of_type(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == event_type]


def _assert_event_mirror(orchestrator: Orchestrator, event_type: str) -> None:
    assert _events_of_type(orchestrator._events, event_type)
    run_events = json.loads("[" + ",".join(
        line for line in (orchestrator._session.path / "events.jsonl").read_text().splitlines()
    ) + "]")
    assert _events_of_type(run_events, event_type) == _events_of_type(
        orchestrator._events, event_type
    )


def test_two_complete_runs_keep_api_and_run_files_isolated(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "runs")
    try:
        payload = {
            "blocks": ["sim_provider"],
            "execution_mode": "stub",
            "standins": {"sim_provider": {"crash_after": 0.05}},
        }
        _, first_config = asyncio.run(request(app, "POST", "/api/config", payload))
        first_run = _run_path(first_config)
        _, first_start = asyncio.run(request(app, "POST", "/api/start"))
        _wait_for_crash(app)
        _, first_stop = asyncio.run(request(app, "POST", "/api/stop"))

        first_file_types = _event_types(first_run / "events.jsonl")
        assert "run_created" in first_file_types
        assert "block_started" in first_file_types
        assert "process_crashed" in first_file_types
        assert "block_stopped" in first_file_types
        assert first_run == _run_path(first_config) == _run_path(first_start) == _run_path(first_stop)

        second_payload = {
            "blocks": ["sim_provider"],
            "execution_mode": "stub",
        }
        _, second_config = asyncio.run(request(app, "POST", "/api/config", second_payload))
        second_run = _run_path(second_config)
        assert second_run != first_run
        assert not ({"crash", "block_stopped"} & {
            event["type"] for event in second_config["events"]
        })
        assert all(event["type"] not in {"block_started", "process_crashed"}
                   for event in second_config["events"])

        _, second_start = asyncio.run(request(app, "POST", "/api/start"))
        _, second_state = asyncio.run(request(app, "GET", "/api/state"))
        _, second_stop = asyncio.run(request(app, "POST", "/api/stop"))
        _, second_final_state = asyncio.run(request(app, "GET", "/api/state"))

        for response in (second_config, second_start, second_stop, second_state, second_final_state):
            assert _run_path(response) == second_run
            assert all(event["type"] not in {"crash", "process_crashed"}
                       for event in response["events"])
        assert second_state["events"] == second_start["events"]
        assert second_final_state["events"] == second_stop["events"]

        second_file_types = _event_types(second_run / "events.jsonl")
        assert "run_created" in second_file_types
        assert "block_started" in second_file_types
        assert "block_stopped" in second_file_types
        assert "process_crashed" not in second_file_types
        assert not (set(first_file_types) - {"run_created", "configured", "block_started",
                                              "process_crashed", "block_stopped"})
    finally:
        app.state.orchestrator.close()


def test_crash_and_stop_events_share_the_run_local_object_with_memory(tmp_path: Path) -> None:
    orchestrator = Orchestrator(run_root=tmp_path)
    try:
        orchestrator.configure({
            "blocks": ["sim_provider"], "execution_mode": "stub",
            "standins": {"sim_provider": {"crash_after": 0.05}},
        })
        orchestrator.start_node("sim_provider")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and orchestrator._nodes["sim_provider"].actual != "crashed":
            time.sleep(0.01)
        assert orchestrator._nodes["sim_provider"].actual == "crashed"
        orchestrator.stop_node("sim_provider")

        _assert_event_mirror(orchestrator, "block_started")
        _assert_event_mirror(orchestrator, "process_crashed")
        _assert_event_mirror(orchestrator, "block_stopped")
        assert not _events_of_type(orchestrator._events, "crash")
    finally:
        orchestrator.close()


def test_cleanup_failed_event_shares_the_run_local_object_with_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        orchestrator_module,
        "stop_process_group",
        lambda *_args, **_kwargs: TeardownResult("cleanup_failed", (987654,), None),
    )
    orchestrator = Orchestrator(run_root=tmp_path)
    try:
        orchestrator.configure({"blocks": ["sim_provider"], "execution_mode": "stub"})
        orchestrator.start_node("sim_provider")
        stopped = orchestrator.stop_node("sim_provider")
        assert stopped["state"]["actual"] == "cleanup_failed"
        _assert_event_mirror(orchestrator, "block_cleanup_failed")
        assert not _events_of_type(orchestrator._events, "block_stopped")
    finally:
        monkeypatch.undo()
        orchestrator.close()
