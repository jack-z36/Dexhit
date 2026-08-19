"""Deterministic software-provider fault injection over public ROS seams."""

import pytest

from omnihand_o10_contracts import Side
from rokoko_omnihand_msgs.msg import O10ControlState
from rokoko_omnihand_msgs.srv import ControlOperation

from rokoko_omnihand_system_test.graph import RosGraph


@pytest.fixture
def graph():
    value = RosGraph.start()
    try:
        yield value
    finally:
        value.close()


@pytest.fixture
def restart_graph():
    value = RosGraph.start(
        control_overrides={
            Side.RIGHT: {
                "provider_heartbeat_timeout": 0.02,
                "error_query_timeout": 0.2,
            }
        }
    )
    try:
        yield value
    finally:
        value.close()


def _make_ready_and_motion(graph: RosGraph, side=Side.RIGHT):
    graph.send_scene(sequence=100)
    assert graph.spin_until(lambda: bool(graph.retargeting_states[side.value]))
    assert graph.spin_until(
        lambda: any(
            state.feedback_ready and state.error_monitor_ready
            for state in graph.control_states[side.value]
        )
    )
    graph.publish_target(side)
    if not graph.spin_until(
        lambda: any(state.target_ready for state in graph.control_states[side.value])
    ):
        if any(
            state.phase == O10ControlState.PHASE_MODEL_ERROR
            for state in graph.retargeting_states[side.value]
        ):
            pytest.skip(
                "successful UDP-to-soft-target path is blocked by the external "
                "O10 model/Pinocchio prerequisites"
            )
        pytest.fail("public control target did not become ready")
    assert graph.spin_until(
        lambda: any(state.motion_enabled for state in graph.control_states[side.value])
    )


def _fault_mask(graph: RosGraph, side=Side.RIGHT) -> int:
    states = graph.control_states[side.value]
    assert states
    return int(states[-1].fault_reason_mask)


def test_error_bit_latches_fault_and_disables_motion(graph):
    _make_ready_and_motion(graph)
    graph.inject(Side.RIGHT, "error_bits")
    assert graph.spin_until(
        lambda: any(state.fault_latched for state in graph.control_states["right"])
    )
    state = graph.control_states["right"][-1]
    assert state.phase == O10ControlState.PHASE_FAULT_LATCHED
    assert not state.motion_enabled
    assert state.fault_reason_mask & O10ControlState.FAULT_HARDWARE_ERROR


@pytest.mark.parametrize(
    "injection,reason",
    [
        ("error_query_timeout", O10ControlState.FAULT_ERROR_MONITOR_TIMEOUT),
        ("command_readback_timeout", O10ControlState.FAULT_COMMAND_READBACK_TIMEOUT),
        ("invalid_feedback", O10ControlState.FAULT_INVALID_FEEDBACK),
    ],
)
def test_runtime_fault_injections_latch_public_control_fault(graph, injection, reason):
    _make_ready_and_motion(graph)
    graph.inject(Side.RIGHT, injection)
    graph.publish_target(Side.RIGHT)
    assert graph.spin_until(
        lambda: any(state.fault_latched for state in graph.control_states["right"])
    )
    assert _fault_mask(graph) & reason


@pytest.mark.parametrize(
    "mode,expected_code",
    [
        (
            "error_query_timeout",
            ControlOperation.Response.CLEAR_FAULT_REJECTED_ERROR_QUERY_TIMEOUT,
        ),
        (
            "feedback_read_timeout",
            ControlOperation.Response.CLEAR_FAULT_REJECTED_FEEDBACK_READ_TIMEOUT,
        ),
        (
            "invalid_error_status",
            ControlOperation.Response.CLEAR_FAULT_REJECTED_ERROR_STATUS_INVALID,
        ),
        (
            "invalid_feedback",
            ControlOperation.Response.CLEAR_FAULT_REJECTED_FEEDBACK_INVALID,
        ),
    ],
)
def test_clear_fault_rejects_deterministic_provider_failures(
        graph, mode, expected_code
):
    _make_ready_and_motion(graph)
    graph.inject(Side.RIGHT, "error_bits")
    assert graph.spin_until(
        lambda: any(state.fault_latched for state in graph.control_states["right"])
    )
    graph.inject(Side.RIGHT, "healthy")
    graph.inject(Side.RIGHT, mode)
    result = graph.call_operation(Side.RIGHT, "clear_fault")
    assert not result.success
    assert result.result_code == expected_code
    assert result.state.fault_latched


def test_clear_fault_reports_hardware_error_still_present(graph):
    _make_ready_and_motion(graph)
    graph.inject(Side.RIGHT, "error_bits")
    assert graph.spin_until(
        lambda: any(state.fault_latched for state in graph.control_states["right"])
    )
    result = graph.call_operation(Side.RIGHT, "clear_fault")
    assert result.result_code == (
        ControlOperation.Response.CLEAR_FAULT_REJECTED_HARDWARE_ERROR_PRESENT
    )
    assert result.state.fault_latched


@pytest.mark.parametrize("mode", ["disconnect", "restart"])
def test_provider_disconnect_and_restart_latch_component_fault(restart_graph, mode):
    _make_ready_and_motion(restart_graph)
    restart_graph.inject(Side.RIGHT, mode)
    assert restart_graph.spin_until(
        lambda: any(
            state.fault_latched
            for state in restart_graph.control_states["right"]
        ),
        timeout_sec=1.0,
    )
    assert _fault_mask(restart_graph) & O10ControlState.FAULT_COMPONENT_RESTART_OR_DISCONNECT
