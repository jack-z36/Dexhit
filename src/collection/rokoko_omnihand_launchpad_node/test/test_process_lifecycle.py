import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rokoko_omnihand_launchpad.process_lifecycle import (
    ProcessMember,
    TeardownResult,
    spawn_managed_process,
    stop_process_group,
)


PYTHON = sys.executable


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _spawn(script, *args, pdeathsig=None):
    return spawn_managed_process(
        [PYTHON, "-c", script, *args],
        os.devnull,
        pdeathsig=pdeathsig,
    )


def test_spawn_creates_session_leader_and_keeps_grandchild_in_group(tmp_path):
    child_pid_file = tmp_path / "grandchild.pid"
    script = (
        "import os, pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
    )
    process = _spawn(script, str(child_pid_file))
    try:
        _wait_until(child_pid_file.exists)
        grandchild_pid = int(child_pid_file.read_text())
        assert os.getpgid(process.pid) == process.pid
        assert os.getsid(process.pid) == process.pid
        assert os.getpgid(grandchild_pid) == process.pid
    finally:
        stop_process_group(process.pid, process, 0.5, 0.5)


def test_stop_process_group_terms_process_tree_and_reaps_launcher(tmp_path):
    child_pid_file = tmp_path / "grandchild.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
    )
    process = _spawn(script, str(child_pid_file))
    _wait_until(child_pid_file.exists)
    grandchild_pid = int(child_pid_file.read_text())

    result = stop_process_group(process.pid, process, 0.5, 0.5)

    assert result == TeardownResult("stopped", (), -signal.SIGTERM)
    assert process.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)


def test_stop_process_group_kills_term_ignoring_group(tmp_path):
    ready = tmp_path / "ready"
    script = (
        "import pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
    )
    process = _spawn(script, str(ready))
    _wait_until(ready.exists)
    result = stop_process_group(process.pid, process, 0.05, 0.5, poll_interval=0.01)

    assert result.outcome == "stopped"
    assert result.remaining_pids == ()
    assert result.exit_code == -signal.SIGKILL


def test_stop_process_group_reports_injected_nonconverging_member():
    class FakeProcess:
        pid = 42

        def poll(self):
            return None

        def wait(self, timeout=None):
            raise TimeoutError

    def probe(_pgid):
        return [ProcessMember(999, "S")]

    signals_sent = []
    result = stop_process_group(
        42,
        FakeProcess(),
        0.01,
        0.01,
        probe=probe,
        signal_group=lambda pgid, sig: signals_sent.append((pgid, sig)),
        poll_interval=0.001,
    )

    assert result.outcome == "cleanup_failed"
    assert result.remaining_pids == (999,)
    assert signals_sent == [(-42, signal.SIGTERM), (-42, signal.SIGKILL)]


def test_zombie_members_do_not_block_stopped_result():
    result = stop_process_group(
        42,
        None,
        0.01,
        0.01,
        probe=lambda _pgid: [ProcessMember(999, "Z")],
        signal_group=lambda _pgid, _sig: pytest.fail("empty zombie group must not be signaled"),
    )

    assert result == TeardownResult("stopped", (), None)


def test_spawn_calls_pdeathsig_after_session_setup(tmp_path):
    marker = tmp_path / "pdeathsig-called"
    script = "import time; time.sleep(30)"

    def injected_pdeathsig():
        Path(marker).write_text(f"{os.getsid(os.getpid())}:{os.getpid()}")

    process = _spawn(script, pdeathsig=injected_pdeathsig)
    try:
        _wait_until(marker.exists)
    finally:
        stop_process_group(process.pid, process, 0.5, 0.5)
    assert marker.read_text() == f"{process.pid}:{process.pid}"


def test_pdeath_guard_kills_grandchildren_when_parent_dies(tmp_path):
    """编排器死亡时 guard 必须清掉 ros2 run 派生的孙进程，不得留 ROS 图孤儿。"""
    grandchild_pid_file = tmp_path / "grandchild.pid"
    parent_script = (
        "import sys, time\n"
        "from rokoko_omnihand_launchpad.process_lifecycle import spawn_managed_process\n"
        "guarded = [sys.executable, '-m', 'rokoko_omnihand_launchpad.pdeath_guard', '--',\n"
        f"           sys.executable, '-c', \"import pathlib, subprocess, sys, time; "
        f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path({str(grandchild_pid_file)!r}).write_text(str(c.pid)); time.sleep(30)\"]\n"
        f"spawn_managed_process(guarded, {str(tmp_path / 'guarded.log')!r}, pdeathsig=lambda: None)\n"
        "time.sleep(30)\n"
    )
    parent = subprocess.Popen([PYTHON, "-c", parent_script], env=os.environ.copy())
    try:
        _wait_until(grandchild_pid_file.exists, timeout=5.0)
        grandchild_pid = int(grandchild_pid_file.read_text())
        os.kill(grandchild_pid, 0)  # 孙进程在父死亡前存活
    except Exception:
        parent.kill()
        parent.wait()
        raise
    parent.kill()  # SIGKILL 编排器进程，模拟最坏退出路径
    parent.wait()
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)
