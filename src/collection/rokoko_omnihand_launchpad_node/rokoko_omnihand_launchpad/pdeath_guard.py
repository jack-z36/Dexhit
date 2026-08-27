"""Parent-death guard: extend PDEATHSIG coverage to grandchildren.

``spawn_managed_process`` arms PR_SET_PDEATHSIG on its direct child only.
Business nodes are started through ``ros2 run`` / wrapper scripts that spawn
the real process as their own child, so when the orchestrator dies the direct
child is SIGKILLed and the real node process is orphaned (it stays in the ROS
graph and blocks later starts).  The guard runs as the direct child instead:
on parent death it receives SIGTERM, forwards it to the whole process group,
escalates to SIGKILL after a bounded wait, and only then exits.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time


PR_SET_PDEATHSIG = 1
ESCALATION_TIMEOUT_SEC = 5.0

_child: subprocess.Popen[bytes] | None = None


def _arm_pdeathsig() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")


def _forward_to_group(signum: int, _frame: object) -> None:
    global _child
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        os.killpg(0, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + ESCALATION_TIMEOUT_SEC
    while _child is not None and _child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if _child is not None and _child.poll() is None:
        try:
            os.killpg(0, signal.SIGKILL)
        except ProcessLookupError:
            pass
    sys.exit(128 + signum)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[2:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: pdeath_guard -- COMMAND [ARGS...]")
    _arm_pdeathsig()
    if os.getppid() == 1:
        # 父进程在 prctl 之前已经退出：内核无法补发信号，自行触发清理。
        _forward_to_group(signal.SIGTERM, None)
    signal.signal(signal.SIGTERM, _forward_to_group)
    global _child
    _child = subprocess.Popen(args)
    sys.exit(_child.wait())


if __name__ == "__main__":
    main()
