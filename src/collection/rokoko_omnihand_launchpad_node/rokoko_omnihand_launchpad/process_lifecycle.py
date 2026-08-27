"""Process-group lifecycle primitives for launchpad-managed commands."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TextIO


@dataclass(frozen=True)
class ProcessMember:
    pid: int
    state: str


@dataclass(frozen=True)
class TeardownResult:
    outcome: str
    remaining_pids: tuple[int, ...]
    exit_code: int | None


def _set_pdeathsig() -> None:
    """Make a child die when its orchestrator parent dies (Linux only)."""
    if sys.platform != "linux":
        return
    parent_pid = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    pr_set_pdeathsig = 1
    if libc.prctl(pr_set_pdeathsig, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def spawn_managed_process(
    command: Iterable[str],
    log_file: str | os.PathLike[str] | int | TextIO,
    *,
    pdeathsig: Callable[[], None] | None = None,
    **popen_kwargs,
) -> subprocess.Popen:
    """Start ``command`` as a session leader with a dedicated process group."""
    if sys.platform != "linux":
        raise OSError("managed process sessions require Linux")

    pdeathsig = _set_pdeathsig if pdeathsig is None else pdeathsig

    def preexec() -> None:
        os.setsid()
        pdeathsig()

    opened_log = None
    stdout = log_file
    if isinstance(log_file, (str, os.PathLike)):
        opened_log = open(log_file, "ab")
        stdout = opened_log
    try:
        return subprocess.Popen(
            list(command),
            stdout=stdout,
            stderr=subprocess.STDOUT,
            preexec_fn=preexec,
            **popen_kwargs,
        )
    finally:
        if opened_log is not None:
            opened_log.close()


def _proc_members(pgid: int) -> list[ProcessMember]:
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            end_name = stat.rfind(")")
            fields = stat[end_name + 2 :].split()
            state = fields[0]
            entry_pgid = int(fields[2])
        except (OSError, ValueError, IndexError):
            continue
        if entry_pgid == pgid:
            members.append(ProcessMember(int(entry.name), state))
    return members


def _live_pids(probe: Callable[[int], Iterable[ProcessMember]], pgid: int) -> tuple[int, ...]:
    return tuple(sorted(member.pid for member in probe(pgid) if member.state != "Z"))


def stop_process_group(
    pgid: int,
    process: subprocess.Popen | None,
    term_timeout: float,
    kill_timeout: float,
    *,
    probe: Callable[[int], Iterable[ProcessMember]] = _proc_members,
    signal_group: Callable[[int, int], None] = os.kill,
    poll_interval: float = 0.01,
) -> TeardownResult:
    """Converge a process group with TERM, bounded wait, then KILL."""
    exit_code = process.poll() if process is not None else None

    def refresh() -> tuple[int, ...]:
        nonlocal exit_code
        if process is not None:
            polled = process.poll()
            if polled is not None:
                exit_code = polled
        return _live_pids(probe, pgid)

    remaining = refresh()
    if remaining:
        try:
            signal_group(-pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        remaining = _wait_for_empty(refresh, term_timeout, poll_interval)

    if remaining:
        try:
            signal_group(-pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        remaining = _wait_for_empty(refresh, kill_timeout, poll_interval)

    # A launcher can become waitable just after the group scan.
    if process is not None and process.poll() is not None:
        exit_code = process.returncode
    return TeardownResult("stopped" if not remaining else "cleanup_failed", remaining, exit_code)


def _wait_for_empty(
    refresh: Callable[[], tuple[int, ...]], timeout: float, poll_interval: float
) -> tuple[int, ...]:
    deadline = time.monotonic() + max(0.0, timeout)
    remaining = refresh()
    while remaining and time.monotonic() < deadline:
        time.sleep(min(max(0.0, poll_interval), max(0.0, deadline - time.monotonic())))
        remaining = refresh()
    return remaining
