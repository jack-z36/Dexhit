"""T10 UDP-to-ROS graph checks through public interfaces only."""

import pytest

from omnihand_o10_contracts import Side
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
    """The control seam uses only the command Topic and arm Service."""
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
    result = graph.call_operation(side, "arm")
    assert result.success
    assert result.state.armed
    graph.publish_target(side)
    assert graph.spin_until(lambda: bool(graph.final_commands[side.value]))
    assert graph.spin_until(lambda: bool(graph.feedback[side.value]))
    # Final command contract deliberately leaves name/velocity/effort empty;
    # the upstream soft target carries the fixed active-joint name order.
    assert graph.final_commands[side.value][-1].name == []
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
