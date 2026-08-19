"""T10 UDP-to-ROS graph checks through public interfaces only."""

import json
import os
import statistics
import time

import pytest
import rclpy

from omnihand_o10_contracts import ACTIVE_JOINT_NAMES, Side
from rokoko_omnihand_msgs.msg import RetargetingState

from rokoko_omnihand_system_test.graph import RosGraph


@pytest.fixture
def graph():
    value = RosGraph.start()
    try:
        yield value
    finally:
        value.close()


def test_udp_receiver_publishes_both_sides_into_real_graph(graph):
    """A JSON-v3 datagram crosses UDP and becomes two public Raw topics."""
    graph.send_scene(sequence=1)
    assert graph.spin_until(
        lambda: len(graph.raw_frames["left"]) >= 1
        and len(graph.raw_frames["right"]) >= 1
    )

    left = graph.raw_frames["left"][-1]
    right = graph.raw_frames["right"][-1]
    assert left.actor_name == "T10FixtureActor"
    assert right.actor_name == "T10FixtureActor"
    assert len(left.node_names) == len(left.positions) == len(left.orientations) == 21
    assert list(left.node_names)[0] == "leftHand"
    assert list(right.node_names)[0] == "rightHand"
    assert left.header.stamp.sec > 0 or left.header.stamp.nanosec > 0


def test_udp_datagram_is_observable_at_retargeting_public_state(graph):
    """The real retargeting node reports either progress or an explicit model block."""
    graph.send_scene(sequence=2)
    assert graph.spin_until(lambda: bool(graph.retargeting_states["right"]))
    state = graph.retargeting_states["right"][-1]
    assert state.side == "right"
    assert state.phase in {
        RetargetingState.PHASE_INITIALIZING,
        RetargetingState.PHASE_COLLECTING_LENGTHS,
        RetargetingState.PHASE_WAITING_FIRST_VALID_IK,
        RetargetingState.PHASE_TRACKING,
        RetargetingState.PHASE_MODEL_ERROR,
    }
    if state.phase == RetargetingState.PHASE_MODEL_ERROR:
        pytest.skip(
            "full UDP→IK→command path is blocked by the installed O10 model/"
            "Pinocchio prerequisites; model-error is observed honestly"
        )
    assert state.input_stamp.sec > 0 or state.input_stamp.nanosec > 0


def test_public_control_topic_and_services_reach_software_provider(graph):
    """The control seam uses only the command Topic (motion is arm-free)."""
    side = Side.RIGHT
    assert graph.spin_until(
        lambda: any(
            state.feedback_ready and state.error_monitor_ready
            for state in graph.control_states[side.value]
        )
    )
    graph.send_scene(sequence=100)
    assert graph.spin_until(lambda: bool(graph.retargeting_states[side.value]))
    graph.publish_target(side)
    if not graph.spin_until(
        lambda: any(state.target_ready for state in graph.control_states[side.value])
    ):
        if any(
            state.phase == RetargetingState.PHASE_MODEL_ERROR
            for state in graph.retargeting_states[side.value]
        ):
            pytest.skip(
                "successful UDP-to-soft-target path is blocked by the external "
                "O10 model/Pinocchio prerequisites"
            )
        pytest.fail("public control target did not become ready")
    graph.publish_target(side)
    assert graph.spin_until(lambda: bool(graph.final_commands[side.value]))
    assert graph.spin_until(lambda: bool(graph.feedback[side.value]))
    # The vendor provider requires the fixed active-joint order on the wire,
    # so the final command carries the fixed active-joint names and leaves
    # velocity/effort empty.
    assert graph.final_commands[side.value][-1].name == list(ACTIVE_JOINT_NAMES)
    assert any(
        state.command_published and state.motion_enabled
        for state in graph.control_states[side.value]
    )


def test_left_and_right_public_control_states_are_independent(graph):
    assert graph.spin_until(
        lambda: all(
            any(state.feedback_ready for state in graph.control_states[side])
            for side in ("left", "right")
        )
    )
    graph.inject(Side.RIGHT, "error_bits")
    assert graph.spin_until(
        lambda: any(
            state.fault_latched for state in graph.control_states["right"]
        )
    )
    assert not any(state.fault_latched for state in graph.control_states["left"])
    assert all(
        state.side in ("left", "right")
        for states in graph.control_states.values()
        for state in states
    )


def test_public_state_has_no_private_node_dependency(graph):
    """The assertion seam is the declared state Topic, never a node callback."""
    graph.send_scene(sequence=3, left=False, right=True)
    assert graph.spin_until(lambda: bool(graph.raw_frames["right"]))
    assert not graph.raw_frames["left"]
    assert graph.retargeter.get_name() == "hand_retargeting"
    assert graph.control.get_name() == "o10_control_node"
    assert graph.receiver.get_name() == "rokoko_hand_receiver"
    assert graph.provider.get_name() == "software_o10_provider"


def test_two_public_graphs_start_and_close_in_one_process():
    """A closed graph does not own or tear down the next graph's context."""
    first = RosGraph.start()
    try:
        first.send_scene(sequence=200)
        assert first.spin_until(
            lambda: bool(first.raw_frames["right"])
            and bool(first.retargeting_states["right"])
        )
        first_port = first.udp_port
        first_executor = first.executor
        first_observer = first.observer
    finally:
        first.close()

    assert rclpy.ok()

    second = RosGraph.start()
    try:
        assert second.executor is not first_executor
        assert second.observer is not first_observer
        assert second.udp_port != first_port
        second.send_scene(sequence=201)
        assert second.spin_until(
            lambda: bool(second.raw_frames["right"])
            and bool(second.retargeting_states["right"])
        )
    finally:
        second.close()


def _stamp_ns(message):
    stamp = message.header.stamp if hasattr(message, "header") else message
    return stamp.sec * 1_000_000_000 + stamp.nanosec


def _percentile(values, percentile):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((percentile / 100) * len(ordered)) - 1))]


def _run_calibrated_replay(graph, *, start_sequence, frames=24):
    phases = {"left": [], "right": []}
    for sequence in range(start_sequence, start_sequence + frames):
        graph.send_calibrated_scene(sequence=sequence)
        assert graph.spin_until(
            lambda: len(graph.raw_frames["left"]) >= sequence - start_sequence + 1
            and len(graph.raw_frames["right"]) >= sequence - start_sequence + 1
        )
        for side in ("left", "right"):
            if graph.retargeting_states[side]:
                phases[side].append(graph.retargeting_states[side][-1].phase)
    assert all(
        any(state.phase == RetargetingState.PHASE_TRACKING
            for state in graph.retargeting_states[side])
        for side in ("left", "right")
    )
    return phases


def test_calibrated_public_replay_reaches_tracking_and_emits_contract_commands(graph):
    phases = _run_calibrated_replay(graph, start_sequence=100, frames=40)
    for side in ("left", "right"):
        assert RetargetingState.PHASE_COLLECTING_LENGTHS in phases[side]
        tracking = [
            state for state in graph.retargeting_states[side]
            if state.phase == RetargetingState.PHASE_TRACKING
        ]
        assert tracking
        assert all(tracking[-1].length_state)
        assert all(tracking[-1].has_valid_ik)
        assert any(
            applied or (available and distance == pytest.approx(0.0))
            for state in tracking
            for applied, available, distance in zip(
                state.target_projection_applied,
                state.target_projection_distance_available,
                state.normalized_target_projection_distance,
            )
        )
        commands = graph.soft_commands[side]
        assert commands
        for command in commands:
            assert len(command.name) == 10
            assert len(command.position) == 10
            assert len(command.velocity) == 0
            assert len(command.effort) == 0
            assert any(_stamp_ns(raw) == _stamp_ns(command)
                       for raw in graph.raw_frames[side])

    artifact_dir = os.environ.get("TASK006_ARTIFACT_DIR")
    if artifact_dir:
        path = os.path.join(artifact_dir, "public_replay_observations.json")
        os.makedirs(artifact_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({
                "phases": phases,
                "states": {
                    side: [
                        {
                            "phase": state.phase,
                            "input_stamp_ns": _stamp_ns(state.input_stamp),
                            "target_projection_applied": list(state.target_projection_applied),
                            "target_projection_distance_available": list(
                                state.target_projection_distance_available
                            ),
                            "normalized_target_projection_distance": list(
                                state.normalized_target_projection_distance
                            ),
                            "normalized_residual": list(state.normalized_residual),
                            "has_valid_ik": list(state.has_valid_ik),
                            "solve_duration_sec": state.solve_duration_sec,
                        }
                        for state in graph.retargeting_states[side]
                    ]
                    for side in ("left", "right")
                },
                "commands": {
                    side: [
                        {
                            "header_stamp_ns": _stamp_ns(command),
                            "name": list(command.name),
                            "position": list(command.position),
                            "velocity_count": len(command.velocity),
                            "effort_count": len(command.effort),
                        }
                        for command in graph.soft_commands[side]
                    ]
                    for side in ("left", "right")
                },
                "counts": {
                    side: {
                        "p1": len(graph.raw_frames[side]),
                        "p2": len(graph.retargeting_states[side]),
                        "p3": len(graph.soft_commands[side]),
                    }
                    for side in ("left", "right")
                },
            }, stream, indent=2)


def test_public_invalid_palm_input_does_not_emit_soft_command(graph):
    for sequence in range(300, 304):
        graph.send_calibrated_scene(sequence=sequence, degenerate_palm=True)
        assert graph.spin_until(
            lambda: len(graph.raw_frames["left"]) >= sequence - 299
            and len(graph.raw_frames["right"]) >= sequence - 299
        )
    assert all(not graph.soft_commands[side] for side in ("left", "right"))
    assert any(
        state.phase in (
            RetargetingState.PHASE_COLLECTING_LENGTHS,
            RetargetingState.PHASE_WAITING_FIRST_VALID_IK,
        )
        for side in ("left", "right")
        for state in graph.retargeting_states[side]
    )


def test_three_calibrated_public_replays_record_p1_p2_p3_age_and_solve_metrics(
    graph, tmp_path
):
    metrics = []
    sequence = 400
    for replay in range(3):
        start = {side: len(graph.raw_frames[side]) for side in ("left", "right")}
        state_start = {side: len(graph.retargeting_states[side]) for side in ("left", "right")}
        command_start = {side: len(graph.soft_commands[side]) for side in ("left", "right")}
        _run_calibrated_replay(graph, start_sequence=sequence, frames=40)
        sequence += 100
        replay_metrics = {"replay": replay + 1, "sides": {}}
        for side in ("left", "right"):
            raw = graph.raw_frames[side][start[side]:]
            states = graph.retargeting_states[side][state_start[side]:]
            commands = graph.soft_commands[side][command_start[side]:]
            raw_by_stamp = {_stamp_ns(message): index for index, message in enumerate(raw)}
            ages_ms = []
            header_deltas_ns = []
            for index, command in enumerate(commands):
                stamp = _stamp_ns(command)
                if stamp in raw_by_stamp:
                    raw_index = raw_by_stamp[stamp]
                    ages_ms.append(
                        (graph.soft_command_arrivals_ns[side][command_start[side] + index]
                         - graph.raw_arrivals_ns[side][start[side] + raw_index]) / 1e6
                    )
                    header_deltas_ns.append(_stamp_ns(command) - _stamp_ns(raw[raw_index]))
            solve = [state.solve_duration_sec for state in states if state.solve_executed]
            replay_metrics["sides"][side] = {
                "p1_count": len(raw),
                "p2_count": len(states),
                "p3_count": len(commands),
                "matched_p1_p3": len(ages_ms),
                "unmatched_p3": len(commands) - len(ages_ms),
                "p1_to_p3_age_ms": {
                    "p50": statistics.median(ages_ms),
                    "p95": _percentile(ages_ms, 95),
                    "p99": _percentile(ages_ms, 99),
                } if ages_ms else None,
                "header_stamp_delta_ns": header_deltas_ns,
                "solve_duration_sec": {
                    "p50": statistics.median(solve),
                    "p95": _percentile(solve, 95),
                    "p99": _percentile(solve, 99),
                } if solve else None,
            }
        metrics.append(replay_metrics)
    assert all(
        replay["sides"][side]["p1_count"] > 0
        and replay["sides"][side]["p2_count"] > 0
        and replay["sides"][side]["p3_count"] > 0
        for replay in metrics for side in ("left", "right")
    )
    artifact_dir = os.environ.get("TASK006_ARTIFACT_DIR")
    if artifact_dir:
        os.makedirs(artifact_dir, exist_ok=True)
        with open(os.path.join(artifact_dir, "replay_metrics.json"), "w", encoding="utf-8") as stream:
            json.dump(metrics, stream, indent=2)
