"""TASK-004 common lifecycle regressions using only the local stub process."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rokoko_omnihand_launchpad.orchestrator import BLOCKS, Orchestrator


NON_RECORDER_BLOCKS = tuple(name for name in BLOCKS if name != "recorder")


def _stub_command(name: str, options: dict, *, spawn_child: bool = False,
                  child_ignore_term: bool = False) -> list[str]:
    command = [sys.executable, "-m", "rokoko_omnihand_launchpad.stub_process", name]
    if spawn_child:
        command.append("--spawn-child")
    if child_ignore_term:
        command.append("--child-ignore-term")
    if options.get("crash_after"):
        command += ["--crash-after", str(options["crash_after"])]
    return command


def _recorder_command(_bag: Path, _topics, *, spawn_child: bool = False,
                      child_ignore_term: bool = False) -> list[str]:
    return _stub_command("recorder", {}, spawn_child=spawn_child,
                         child_ignore_term=child_ignore_term)


def _group_members(pgid: int | None) -> set[int]:
    if pgid is None or sys.platform != "linux":
        return set()
    members: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            end_name = stat.rfind(")")
            fields = stat[end_name + 2 :].split()
            if fields[0] != "Z" and int(fields[2]) == pgid:
                members.add(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return members


def _wait_group_empty(pgid: int | None, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _group_members(pgid):
            return
        time.sleep(0.01)
    assert not _group_members(pgid)


def _configure(orchestrator: Orchestrator, blocks, standins=None) -> None:
    payload = {"blocks": list(blocks), "execution_mode": "stub"}
    if standins:
        payload["standins"] = standins
    orchestrator.configure(payload)


def test_each_non_recorder_block_stops_spawned_grandchild_group(tmp_path: Path) -> None:
    for name in NON_RECORDER_BLOCKS:
        orchestrator = Orchestrator(
            command_factory=lambda block, options: _stub_command(block, options, spawn_child=True),
            run_root=tmp_path / name, term_timeout=0.1, kill_timeout=0.5,
        )
        try:
            _configure(orchestrator, [name])
            started = orchestrator.start_node(name)
            pgid = started["pgid"]
            stopped = orchestrator.stop_node(name)["state"]
            assert stopped["actual"] == "stopped"
            assert stopped["pid"] is None and stopped["pgid"] is None
            _wait_group_empty(pgid)
        finally:
            orchestrator.close()


def test_recorder_standin_stops_spawned_grandchild_group(tmp_path: Path) -> None:
    orchestrator = Orchestrator(
        recorder_command_factory=lambda bag, topics: _recorder_command(bag, topics, spawn_child=True),
        run_root=tmp_path, term_timeout=0.1, kill_timeout=0.5,
    )
    try:
        _configure(orchestrator, ["recorder"])
        pgid = orchestrator.start_node("recorder")["pgid"]
        stopped = orchestrator.stop_node("recorder")["state"]
        assert stopped["actual"] == "stopped"
        assert stopped["pid"] is None and stopped["pgid"] is None
        _wait_group_empty(pgid)
    finally:
        orchestrator.close()


def test_ignore_term_grandchild_uses_bounded_kill_fallback(tmp_path: Path) -> None:
    orchestrator = Orchestrator(
        command_factory=lambda block, options: _stub_command(
            block, options, spawn_child=True, child_ignore_term=True),
        run_root=tmp_path, term_timeout=0.05, kill_timeout=0.5,
    )
    try:
        _configure(orchestrator, ["sim_provider"])
        started_at = time.monotonic()
        pgid = orchestrator.start_node("sim_provider")["pgid"]
        state = orchestrator.stop_node("sim_provider")["state"]
        elapsed = time.monotonic() - started_at
        assert state["actual"] == "stopped"
        assert elapsed < 1.0
        _wait_group_empty(pgid)
    finally:
        orchestrator.close()


def test_crash_is_alerted_once_and_explicit_stop_stops(tmp_path: Path) -> None:
    orchestrator = Orchestrator(run_root=tmp_path, term_timeout=0.1, kill_timeout=0.3)
    try:
        _configure(orchestrator, ["sim_provider"], {"sim_provider": {"crash_after": 0.05}})
        first = orchestrator.start_node("sim_provider")
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] == "crashed":
                break
            time.sleep(0.01)
        crashed = orchestrator.snapshot()["nodes"]["sim_provider"]
        assert crashed["actual"] == "crashed"
        assert "not restarted" in crashed["alert"]
        assert crashed["pid"] == first["pid"]
        time.sleep(0.1)
        assert orchestrator.snapshot()["nodes"]["sim_provider"]["pid"] == first["pid"]
        assert orchestrator.stop_node("sim_provider")["state"]["actual"] == "stopped"
    finally:
        orchestrator.close()


def test_same_configuration_can_complete_two_start_stop_rounds(tmp_path: Path) -> None:
    orchestrator = Orchestrator(
        command_factory=lambda block, options: _stub_command(block, options, spawn_child=True),
        run_root=tmp_path, term_timeout=0.1, kill_timeout=0.5,
    )
    try:
        blocks = ("rokoko_receiver", "hand_retargeting", "omnihand_o10_control",
                  "sim_provider", "synthetic_input")
        _configure(orchestrator, blocks)
        for _round in range(2):
            started = orchestrator.start_all()
            pgids = [started["nodes"][name]["pgid"] for name in blocks]
            stopped = orchestrator.stop_all()
            assert all(stopped["nodes"][name]["actual"] == "stopped" for name in blocks)
            for pgid in pgids:
                _wait_group_empty(pgid)
    finally:
        orchestrator.close()


@pytest.mark.parametrize("blocks", (
    tuple(name for name in BLOCKS if name != "hcan_provider"),
    tuple(name for name in BLOCKS if name not in {"sim_provider", "synthetic_input"}),
))
def test_pdeathsig_parent_death_releases_all_block_groups(tmp_path: Path, blocks) -> None:
    marker = tmp_path / "ready.json"
    script = r'''
import json, pathlib, sys, time
from rokoko_omnihand_launchpad.orchestrator import BLOCKS, Orchestrator

def command(name, _options):
    return [sys.executable, "-m", "rokoko_omnihand_launchpad.stub_process", name, "--spawn-child"]

o = Orchestrator(command_factory=command, run_root=pathlib.Path(%r), term_timeout=.1, kill_timeout=.2)
blocks = %r
o.configure({"blocks": blocks, "execution_mode": "stub"})
snapshot = o.start_all()
pathlib.Path(%r).write_text(json.dumps([snapshot["nodes"][name]["pgid"] for name in blocks]))
time.sleep(30)
''' % (str(tmp_path / "child-run"), tuple(blocks), str(marker))
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": "src/collection/rokoko_omnihand_launchpad_node"},
    )
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.01)
        assert marker.exists()
        pgids = json.loads(marker.read_text())
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=1.0)
        for pgid in pgids:
            _wait_group_empty(pgid, timeout=1.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1.0)
