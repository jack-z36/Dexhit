"""Small executable stand-in used by Launchpad integration tests and dev mode."""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time


def _set_pdeathsig() -> None:
    """Make a spawned test descendant die with this stub process."""
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("--crash-after", type=float, default=0)
    parser.add_argument("--spawn-child", action="store_true")
    parser.add_argument("--child-ignore-term", action="store_true")
    parser.add_argument("--ignore-term", action="store_true")
    args = parser.parse_args()
    if args.delay:
        time.sleep(args.delay)
    if args.spawn_child:
        child_command = [sys.executable, "-m", "rokoko_omnihand_launchpad.stub_process",
                         f"{args.name}-grandchild"]
        if args.child_ignore_term:
            child_command.append("--ignore-term")
        subprocess.Popen(child_command, preexec_fn=_set_pdeathsig)
    deadline = time.monotonic() + args.crash_after if args.crash_after else None
    if args.ignore_term or args.child_ignore_term:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, lambda *_: raise_system_exit())
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return 17
        time.sleep(0.05)


def raise_system_exit() -> None:
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())
