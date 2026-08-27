"""TASK-002 startup tests using local stand-ins only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rokoko_omnihand_launchpad.orchestrator import BLOCKS, Orchestrator


def _sleep_command(*_args):
    return [sys.executable, "-c", "import time; time.sleep(10)"]


def test_all_managed_blocks_start_in_distinct_session_groups(tmp_path: Path) -> None:
    def recorder_command(_bag: Path, _topics):
        return [sys.executable, "-c", "import time; time.sleep(10)"]

    orchestrator = Orchestrator(
        command_factory=_sleep_command,
        recorder_command_factory=recorder_command,
        run_root=tmp_path / "runs",
    )
    try:
        orchestrator.configure({"blocks": [], "execution_mode": "stub"})
        for name in BLOCKS:
            orchestrator.start_node(name)
        snapshot = orchestrator.snapshot()
        launchpad_pgid = os.getpgrp()
        pgids = []
        for name in BLOCKS:
            state = snapshot["nodes"][name]
            assert state["pid"] is not None
            assert state["pgid"] == state["pid"]
            assert os.getpgid(state["pid"]) == state["pid"]
            assert os.getsid(state["pid"]) == state["pid"]
            pgids.append(state["pgid"])
        assert launchpad_pgid not in pgids
        assert len(set(pgids)) == len(BLOCKS)
    finally:
        orchestrator.close()
