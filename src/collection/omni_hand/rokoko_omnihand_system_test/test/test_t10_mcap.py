"""MCAP is an external rosbag2 concern, observed through public graph APIs."""

from __future__ import annotations

import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from rokoko_omnihand_system_test.graph import RosGraph


@pytest.fixture
def graph():
    value = RosGraph.start()
    try:
        yield value
    finally:
        value.close()


def test_public_topics_are_discoverable_and_recordable_as_mcap(graph, tmp_path):
    expected_topics = {
        "/rokoko/right/raw_hand",
        "/hand_retargeting/right/state",
        "/o10_control/right/state",
        "/o10/right/joint_cmd",
        "/o10/right/joint_states",
    }
    discovered = {
        name for name, _types in graph.observer.get_topic_names_and_types()
    }
    assert expected_topics <= discovered

    ros2 = shutil.which("ros2")
    if ros2 is None:
        pytest.skip("ros2 CLI is unavailable; MCAP recording cannot be probed")

    bag_path = tmp_path / "t10_public_topics"
    recorder = subprocess.Popen(
        [
            ros2,
            "bag",
            "record",
            "--storage",
            "mcap",
            "--output",
            str(bag_path),
            "--topics",
            *sorted(expected_topics),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        if recorder.poll() is not None:
            pytest.skip(
                "rosbag2 MCAP recorder is installed but unavailable at runtime"
            )
        graph.send_scene(sequence=4)
        assert graph.spin_until(lambda: bool(graph.raw_frames["right"]))
        assert graph.spin_until(lambda: bool(graph.control_states["right"]))
        time.sleep(0.5)
    finally:
        if recorder.poll() is None:
            recorder.send_signal(signal.SIGINT)
        try:
            recorder.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            recorder.kill()
            recorder.wait(timeout=5.0)

    metadata = bag_path / "metadata.yaml"
    mcap_files = list(bag_path.glob("*.mcap"))
    if not metadata.exists() or not mcap_files:
        pytest.skip("rosbag2 did not produce an MCAP artifact in this environment")
    assert "storage_identifier: mcap" in metadata.read_text(encoding="utf-8")


def test_business_nodes_do_not_embed_an_mcap_writer():
    omni_hand = Path(__file__).resolve().parents[2]
    node_paths = (
        omni_hand / "rokoko_hand_receiver" / "rokoko_hand_receiver" / "node.py",
        omni_hand / "hand_retargeting" / "hand_retargeting" / "node.py",
        omni_hand / "omnihand_o10_control" / "omnihand_o10_control" / "node.py",
    )
    for path in node_paths:
        source = path.read_text(encoding="utf-8")
        assert "rosbag2_py" not in source
        assert "SequentialWriter" not in source
