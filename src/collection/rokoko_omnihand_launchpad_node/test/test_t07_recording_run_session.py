"""T07 observable run-artifact tests; no ROS installation is required."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from rokoko_omnihand_launchpad.recording import Recorder, RecorderUnavailable
from rokoko_omnihand_launchpad.run_session import RunSession
from rokoko_omnihand_launchpad.sysmon import SystemMonitor


def test_run_session_writes_metadata_events_and_thread_safe_log(tmp_path: Path) -> None:
    session = RunSession(tmp_path / "runs" / "launchpad", config={
        "blocks": ["rokoko_receiver"], "template": "data_link", "profile": "default",
        "side": "left", "execution_mode": "stub", "label": "test run",
        "udp_port": 14043,
    })
    session.event("web_mark", label="fault injected")
    session.event("block_started", node="rokoko_receiver")
    session.close()

    metadata = json.loads((session.path / "metadata.json").read_text())
    assert metadata["blocks"] == ["rokoko_receiver"]
    assert metadata["side"] == "left"
    events = [json.loads(line) for line in (session.path / "events.jsonl").read_text().splitlines()]
    assert [event["type"] for event in events] == ["run_created", "web_mark", "block_started"]
    assert session.log_path("rokoko_receiver").parent.is_dir()


def test_sysmon_samples_and_stops_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "sysmon.jsonl"
    monitor = SystemMonitor(path, interval=0.01)
    monitor.start()
    time.sleep(0.04)
    monitor.stop()
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines
    assert all("cpu_percent" in line and "memory_bytes" in line for line in lines)


def test_recorder_command_seam_starts_and_stops_without_ros(tmp_path: Path) -> None:
    def command(bag: Path, topics: tuple[str, ...]) -> list[str]:
        assert "/rosout" in topics
        return [sys.executable, "-c", "import time; time.sleep(10)"]

    recorder = Recorder(tmp_path, command_factory=command)
    recorder.start()
    assert recorder.running
    result = recorder.stop()
    assert result.outcome == "stopped"
    # pdeath_guard 收到组 TERM 后以 128+SIGTERM=143 退出并清理子进程；
    # guard 自身被信号终止时则为 -15。两者都是干净停机。
    assert result.exit_code in (-15, 143)


def test_real_recorder_reports_missing_ros2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("rokoko_omnihand_launchpad.recording.shutil.which", lambda _: None)
    with pytest.raises(RecorderUnavailable, match="ros2 is not available"):
        Recorder(tmp_path).start()
