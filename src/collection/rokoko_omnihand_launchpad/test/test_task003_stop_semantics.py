from __future__ import annotations

import threading
import time
import sys
import subprocess

import pytest

from rokoko_omnihand_launchpad import orchestrator as orchestrator_module
from rokoko_omnihand_launchpad.orchestrator import Orchestrator
from rokoko_omnihand_launchpad.process_lifecycle import TeardownResult


def _configure(orchestrator: Orchestrator, *, standin=None):
    payload = {"blocks": ["sim_provider"], "execution_mode": "stub"}
    if standin is not None:
        payload["standins"] = {"sim_provider": standin}
    orchestrator.configure(payload)


def test_stop_converges_grandchild_group_and_clears_identity(tmp_path):
    child_script = "import time; time.sleep(30)"
    command = lambda _name, _options: [
        sys.executable, "-c",
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); time.sleep(30)" % child_script,
    ]
    orchestrator = Orchestrator(command_factory=command, run_root=tmp_path,
                                term_timeout=0.2, kill_timeout=0.5)
    try:
        _configure(orchestrator)
        started = orchestrator.start_node("sim_provider")
        stopped = orchestrator.stop_node("sim_provider")
        assert stopped["state"]["actual"] == "stopped"
        assert stopped["state"]["pid"] is None
        assert stopped["state"]["pgid"] is None
        assert any(event["type"] == "block_stopped" for event in orchestrator.snapshot()["events"])
        assert started["pid"] is not None
    finally:
        orchestrator.close()


def test_ignore_term_group_uses_kill_fallback(tmp_path):
    command = lambda _name, _options: [
        sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    ]
    orchestrator = Orchestrator(command_factory=command, run_root=tmp_path,
                                term_timeout=0.03, kill_timeout=0.5)
    try:
        _configure(orchestrator)
        orchestrator.start_node("sim_provider")
        time.sleep(0.1)
        state = orchestrator.stop_node("sim_provider")["state"]
        assert state["actual"] == "stopped"
        assert state["exit_code"] == -9
    finally:
        orchestrator.close()


def test_cleanup_failure_is_terminal_and_blocks_restart(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        return TeardownResult("cleanup_failed", (987654,), None)

    monkeypatch.setattr(orchestrator_module, "stop_process_group", fail)
    orchestrator = Orchestrator(run_root=tmp_path)
    try:
        _configure(orchestrator)
        orchestrator.start_node("sim_provider")
        stopped = orchestrator.stop_node("sim_provider")["state"]
        assert stopped["actual"] == "cleanup_failed"
        assert stopped["pgid"] is not None
        assert "987654" in stopped["alert"]
        assert not any(event["type"] == "block_stopped" for event in orchestrator.snapshot()["events"])
        assert any(event["type"] == "block_cleanup_failed" for event in orchestrator.snapshot()["events"])
        with pytest.raises(ValueError, match="cleanup failed"):
            orchestrator.start_node("sim_provider")
    finally:
        # The process is intentionally not stopped through the injected failure.
        monkeypatch.undo()
        orchestrator.close()


def test_watcher_does_not_overwrite_stop_terminal_state(monkeypatch, tmp_path):
    release = threading.Event()
    original = orchestrator_module.stop_process_group

    def delayed(*args, **kwargs):
        release.wait(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(orchestrator_module, "stop_process_group", delayed)
    orchestrator = Orchestrator(run_root=tmp_path, term_timeout=0.2, kill_timeout=0.5)
    try:
        _configure(orchestrator, standin={"crash_after": 0.05})
        orchestrator.start_node("sim_provider")
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("value", orchestrator.stop_node("sim_provider")))
        thread.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] != "stopping":
            time.sleep(0.005)
        assert orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] == "stopping"
        release.set()
        thread.join(2)
        assert result["value"]["state"]["actual"] == "stopped"
    finally:
        release.set()
        orchestrator.close()


def test_old_watcher_cannot_corrupt_immediately_restarted_instance(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    original_wait = subprocess.Popen.wait
    old_pid = None

    def delayed_wait(process, *args, **kwargs):
        code = original_wait(process, *args, **kwargs)
        if process.pid == old_pid:
            entered.set()
            assert release.wait(2)
        return code

    monkeypatch.setattr(subprocess.Popen, "wait", delayed_wait)
    commands = iter((
        "import time; time.sleep(0.05); raise SystemExit(17)",
        "import time; time.sleep(30)",
    ))
    command = lambda _name, _options: [sys.executable, "-c", next(commands)]
    orchestrator = Orchestrator(command_factory=command, run_root=tmp_path,
                                term_timeout=0.1, kill_timeout=0.3)
    try:
        _configure(orchestrator)
        first = orchestrator.start_node("sim_provider")
        old_pid = first["pid"]
        assert entered.wait(2)

        stopped = orchestrator.stop_node("sim_provider")["state"]
        assert stopped["actual"] == "stopped"
        second = orchestrator.start_node("sim_provider")
        assert second["pid"] != old_pid
        assert orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] == "starting"

        release.set()
        time.sleep(0.1)
        state = orchestrator.snapshot()["nodes"]["sim_provider"]
        assert state["pid"] == second["pid"]
        assert state["actual"] == "starting"
        assert state["exit_code"] is None
        assert not any(event["type"] == "crash" for event in orchestrator.snapshot()["events"])
    finally:
        release.set()
        orchestrator.close()


def test_snapshot_is_available_while_stop_waits(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    original = orchestrator_module.stop_process_group

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(orchestrator_module, "stop_process_group", delayed)
    orchestrator = Orchestrator(run_root=tmp_path)
    try:
        _configure(orchestrator)
        orchestrator.start_node("sim_provider")
        thread = threading.Thread(target=orchestrator.stop_node, args=("sim_provider",))
        thread.start()
        assert entered.wait(1)
        assert orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] == "stopping"
        release.set()
        thread.join(2)
    finally:
        release.set()
        orchestrator.close()


def test_crash_is_not_restarted_and_stop_converts_to_stopped(tmp_path):
    orchestrator = Orchestrator(run_root=tmp_path, term_timeout=0.1, kill_timeout=0.3)
    try:
        _configure(orchestrator, standin={"crash_after": 0.05})
        orchestrator.start_node("sim_provider")
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] != "crashed":
            time.sleep(0.01)
        crashed = orchestrator.snapshot()["nodes"]["sim_provider"]
        assert crashed["actual"] == "crashed"
        assert "not restarted" in crashed["alert"]
        stopped = orchestrator.stop_node("sim_provider")["state"]
        assert stopped["actual"] == "stopped"
    finally:
        orchestrator.close()
