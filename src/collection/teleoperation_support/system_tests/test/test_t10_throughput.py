"""Repeatable no-hardware throughput and age measurement."""

from __future__ import annotations

import statistics
import time
import json
import os

import pytest

from rokoko_omnihand_system_test.graph import RosGraph


@pytest.fixture
def graph():
    value = RosGraph.start()
    try:
        yield value
    finally:
        value.close()


def test_udp_to_raw_throughput_and_receive_age_are_recorded(graph):
    """Record a distribution without asserting a hardware or IK target."""
    samples = 20
    receive_counts = {"left": 0, "right": 0}
    start = time.perf_counter()
    for sequence in range(samples):
        graph.send_scene(sequence=sequence)
        assert graph.spin_until(
            lambda: len(graph.raw_frames["left"]) > receive_counts["left"]
            and len(graph.raw_frames["right"]) > receive_counts["right"],
            timeout_sec=1.0,
        )
        receive_counts["left"] = len(graph.raw_frames["left"])
        receive_counts["right"] = len(graph.raw_frames["right"])
    elapsed = time.perf_counter() - start

    assert receive_counts == {"left": samples, "right": samples}
    throughput = (2.0 * samples) / elapsed
    ages_ms = []
    for side in ("left", "right"):
        ages_ms.extend(
            [
                (time.time_ns() - (frame.header.stamp.sec * 1_000_000_000
                                   + frame.header.stamp.nanosec)) / 1e6
                for frame in graph.raw_frames[side]
            ]
        )
    result = {
        "metric": "udp_to_raw",
        "frames_per_second_both_sides": throughput,
        "receive_age_ms_p50": statistics.median(ages_ms),
        "receive_age_ms_p95": sorted(ages_ms)[max(0, int(0.95 * len(ages_ms)) - 1)],
        "samples_per_side": samples,
        "ik_duration": "not measured: model/Pinocchio prerequisite is external",
    }
    print("T10_THROUGHPUT " + repr(result))


def test_calibrated_dual_side_throughput_is_observed(graph):
    samples = []
    sequence = 600
    for replay in range(3):
        start = {side: len(graph.raw_frames[side]) for side in ("left", "right")}
        command_start = {side: len(graph.soft_commands[side]) for side in ("left", "right")}
        began = time.perf_counter()
        for current in range(sequence, sequence + 40):
            graph.send_calibrated_scene(sequence=current)
            assert graph.spin_until(
                lambda: len(graph.raw_frames["left"]) >= start["left"] + (current - sequence + 1)
                and len(graph.raw_frames["right"]) >= start["right"] + (current - sequence + 1)
            )
        elapsed = time.perf_counter() - began
        samples.append({
            "replay": replay + 1,
            "dual_side_p1_count": sum(
                len(graph.raw_frames[side]) - start[side] for side in ("left", "right")
            ),
            "dual_side_p3_count": sum(
                len(graph.soft_commands[side]) - command_start[side]
                for side in ("left", "right")
            ),
            "throughput_hz": 80.0 / elapsed,
        })
        sequence += 100
    values = [sample["throughput_hz"] for sample in samples]
    result = {
        "metric": "calibrated_dual_side_public_replay",
        "replays": samples,
        "throughput_hz": {
            "p50": statistics.median(values),
            "p95": sorted(values)[min(2, len(values) - 1)],
            "p99": sorted(values)[-1],
        },
    }
    assert all(sample["dual_side_p3_count"] > 0 for sample in samples)
    artifact_dir = os.environ.get("TASK006_ARTIFACT_DIR")
    if artifact_dir:
        os.makedirs(artifact_dir, exist_ok=True)
        with open(os.path.join(artifact_dir, "throughput_metrics.json"), "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
