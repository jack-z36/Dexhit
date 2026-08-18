"""MCAP is an external rosbag2 concern, observed through public graph APIs."""

from __future__ import annotations

import shutil
import signal
import subprocess
import time
import os
import json
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
        f"/rokoko/{side}/raw_hand"
        for side in ("left", "right")
    } | {
        f"/hand_retargeting/{side}/state"
        for side in ("left", "right")
    } | {
        f"/o10_control/{side}/command"
        for side in ("left", "right")
    }
    discovered = {
        name for name, _types in graph.observer.get_topic_names_and_types()
    }
    assert expected_topics <= discovered

    ros2 = shutil.which("ros2")
    if ros2 is None:
        pytest.fail("MCAP_BLOCKED: ros2 CLI is unavailable")

    bag_path = Path(
        os.environ.get("TASK006_BAG_PATH", str(tmp_path / "t10_public_topics"))
    )
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(1.0)
        if recorder.poll() is not None:
            pytest.fail("MCAP_BLOCKED: rosbag2 recorder exited before replay")
        for sequence in range(700, 740):
            graph.send_calibrated_scene(sequence=sequence)
            assert graph.spin_until(
                lambda: len(graph.raw_frames["right"]) >= sequence - 699
            )
        time.sleep(1.0)
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
    output = recorder.stdout.read() if recorder.stdout is not None else ""
    artifact_dir = os.environ.get("TASK006_ARTIFACT_DIR")
    if artifact_dir:
        os.makedirs(artifact_dir, exist_ok=True)
        with open(os.path.join(artifact_dir, "mcap_recorder.log"), "w", encoding="utf-8") as stream:
            stream.write(output)
        with open(os.path.join(artifact_dir, "mcap_summary.json"), "w", encoding="utf-8") as stream:
            json.dump({
                "bag_path": str(bag_path),
                "returncode": recorder.returncode,
                "metadata_exists": metadata.exists(),
                "mcap_files": [str(path) for path in mcap_files],
                "mcap_sizes": [path.stat().st_size for path in mcap_files],
            }, stream, indent=2)
    assert recorder.returncode == 0, output
    assert metadata.exists(), "MCAP_BLOCKED: metadata.yaml is missing"
    assert mcap_files, "MCAP_BLOCKED: no .mcap artifact was created"
    assert any(path.stat().st_size > 0 for path in mcap_files), (
        "MCAP_BLOCKED: all .mcap artifacts are empty"
    )
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
