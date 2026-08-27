"""External rosbag2/MCAP recorder owned by a Launchpad run."""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .process_lifecycle import TeardownResult, spawn_managed_process, stop_process_group


PUBLIC_TOPICS: tuple[str, ...] = (
    "/rokoko/left/raw_hand", "/rokoko/right/raw_hand",
    "/hand_retargeting/left/state", "/hand_retargeting/right/state",
    "/o10_control/left/command", "/o10_control/right/command",
    "/o10_control/left/state", "/o10_control/right/state",
    "/o10/left/joint_cmd", "/o10/right/joint_cmd",
    "/o10/left/joint_states", "/o10/right/joint_states",
    "/o10/left/joint_error_states", "/o10/right/joint_error_states",
    "/rosout",
)


class RecorderUnavailable(RuntimeError):
    """The real ros2 recorder cannot be started in the current environment."""


class Recorder:
    def __init__(self, run_path: Path, *, command_factory: Callable[[Path, Sequence[str]], list[str]] | None = None,
                 pdeathsig: Callable[[], None] | None = None) -> None:
        self.run_path = Path(run_path)
        self.command_factory = command_factory
        self.pdeathsig = pdeathsig
        self.process: subprocess.Popen[bytes] | None = None
        self.bag_path = self.run_path / "bag"
        self.log_path = self.run_path / "logs" / "recorder.log"

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def command(self, topics: Sequence[str] = PUBLIC_TOPICS) -> list[str]:
        if self.command_factory:
            return list(self.command_factory(self.bag_path, topics))
        return ["ros2", "bag", "record", "--storage", "mcap", "-o", str(self.bag_path), *topics]

    def start(self, topics: Sequence[str] = PUBLIC_TOPICS) -> subprocess.Popen[bytes]:
        if self.running:
            return self.process  # type: ignore[return-value]
        if self.command_factory is None and shutil.which("ros2") is None:
            raise RecorderUnavailable("ROS 2 command ros2 is not available; MCAP recording was not started")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # ros2 bag CLI 会派生 recorder 子进程；与真节点一样经 pdeath_guard
        # 接管父死亡清理，避免编排器退出后 recorder 孤儿化继续写盘。
        command = [sys.executable, "-m", "rokoko_omnihand_launchpad.pdeath_guard",
                   "--", *self.command(topics)]
        try:
            self.process = spawn_managed_process(command, self.log_path,
                                                 pdeathsig=lambda: None)
        except Exception:
            raise
        return self.process

    def stop(self, *, term_timeout: float = 5.0, kill_timeout: float = 3.0) -> TeardownResult | None:
        process = self.process
        if process is None:
            return None
        return stop_process_group(process.pid, process, term_timeout, kill_timeout)
