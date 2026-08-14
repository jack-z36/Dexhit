"""Repeatable no-hardware throughput and age measurement."""

from __future__ import annotations

import statistics
import time

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
