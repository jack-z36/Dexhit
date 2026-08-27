"""Run history API and filesystem-boundary tests for T08."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from rokoko_omnihand_launchpad.app import create_app
from rokoko_omnihand_launchpad.run_session import RunSession, delete_run_session, list_run_sessions
from test_orchestrator_api import request


def test_run_summary_keeps_template_and_label_and_lists_artifacts(tmp_path: Path) -> None:
    session = RunSession(tmp_path / "runs" / "launchpad", config={"template": "data", "label": "test run", "blocks": []})
    (session.path / "bag").mkdir()
    (session.path / "bag" / "record_0.mcap").write_bytes(b"mcap")
    session.close()

    runs = list_run_sessions(tmp_path / "runs" / "launchpad")
    assert runs[0]["id"].endswith("_data_test_run")
    assert runs[0]["template"] == "data"
    assert runs[0]["label"] == "test run"
    assert {item["kind"] for item in runs[0]["artifacts"]} >= {"mcap", "metadata", "events", "logs"}


def test_delete_run_session_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "launchpad"
    root.mkdir(parents=True)
    (root / "keep").mkdir()
    with pytest.raises(ValueError):
        delete_run_session(root, "../keep")
    assert (root / "keep").is_dir()


def test_runs_api_lists_and_deletes_only_explicit_run(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "launchpad"
    session = RunSession(root, config={"template": "custom", "label": "manual", "blocks": []})
    session.close()
    app = create_app(run_root=root)

    status, result = asyncio.run(request(app, "GET", "/api/runs"))
    assert status == 200 and len(result["runs"]) == 1
    run_id = result["runs"][0]["id"]
    status, result = asyncio.run(request(app, "DELETE", f"/api/runs/{run_id}"))
    assert status == 200 and result["deleted"] == run_id
    assert not (root / run_id).exists()
