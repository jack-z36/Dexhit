"""ROS <-> pure-value adapters for the O10 control node.

This is the ONLY layer (besides the node) that may import ROS messages and
rclpy types (ARCHITECTURE A03 / A21).  It maps between the pure contracts value
objects and the wire schema in ``rokoko_omnihand_msgs`` and ``sensor_msgs``,
translating numeric constants exactly as the single-source enums define them
(ARCHITECTURE A16) -- no numeric literals are duplicated here.
"""

from __future__ import annotations

from builtin_interfaces.msg import Time as RosTime
from rokoko_omnihand_msgs.msg import O10ControlState
from rokoko_omnihand_msgs.srv import ControlOperation, ReadO10ActiveJoints
from sensor_msgs.msg import JointState
from std_msgs.msg import Int16MultiArray

from omnihand_o10_contracts import (
    ACTIVE_JOINT_COUNT,
    JointError,
    JointFeedback,
    JointSampleTime,
    Side,
)

from ..contracts import (
    ArmCode,
    ClearFaultCode,
    ControlStateSnapshot,
    DisarmCode,
    SoftTargetValue,
)

__all__ = [
    "ros_time_to_sample_time",
    "sample_time_to_ros_time",
    "joint_state_to_soft_target",
    "control_state_to_message",
    "error_words_to_joint_error",
    "joint_error_to_error_words",
    "operation_result_to_response",
    "read_response_to_feedback",
    "build_command_message",
    "build_state_message",
]


def _wire_constant(owner, prefix: str, semantic_name: str) -> int:
    """Resolve a semantic enum member through the generated wire constant."""
    return int(getattr(owner, f"{prefix}{semantic_name}"))


def ros_time_to_sample_time(value: RosTime) -> JointSampleTime:
    return JointSampleTime(value.sec + value.nanosec * 1e-9)


def sample_time_to_ros_time(value: JointSampleTime) -> RosTime:
    result = RosTime()
    result.sec = int(value.seconds)
    result.nanosec = int(round((value.seconds - result.sec) * 1e9))
    return result


def joint_state_to_soft_target(
    side: Side, message: JointState, received_at: JointSampleTime
) -> SoftTargetValue:
    """Convert an upstream command JointState into a pre-validation view."""
    return SoftTargetValue(
        side=Side.from_value(side),
        name=tuple(message.name),
        position=tuple(float(value) for value in message.position),
        velocity_empty=len(message.velocity) == 0,
        effort_empty=len(message.effort) == 0,
        frame_id=message.header.frame_id,
        input_stamp=(
            ros_time_to_sample_time(message.header.stamp)
            if message.header.stamp.sec != 0 or message.header.stamp.nanosec != 0
            else None
        ),
        received_at=received_at,
    )


def control_state_to_message(
    state: ControlStateSnapshot, stamp: RosTime
) -> O10ControlState:
    """Map a pure snapshot onto the wire O10ControlState message."""
    result = O10ControlState()
    result.header.stamp = stamp

    result.side = state.side.value
    result.event = _wire_constant(O10ControlState, "EVENT_", state.trigger.name)
    result.phase = _wire_constant(O10ControlState, "PHASE_", state.phase.name)

    result.feedback_ready = state.feedback_ready
    result.error_monitor_ready = state.error_monitor_ready
    result.target_ready = state.target_ready
    result.target_fresh = state.target_fresh

    result.armed = state.armed
    result.fault_latched = state.fault_latched
    result.motion_enabled = state.motion_enabled

    result.target_result = _wire_constant(
        O10ControlState, "TARGET_", state.target_result.name
    )
    result.command_published = state.command_published
    result.slew_limited = list(state.slew_limited)
    result.fault_reason_mask = 0
    for reason in state.fault_reasons:
        result.fault_reason_mask |= _wire_constant(
            O10ControlState, "FAULT_", reason.name
        )
    result.hardware_error_bits = [int(value) for value in state.hardware_error_bits]

    result.target_time_available = state.last_target_input_stamp is not None
    result.last_target_input_stamp = (
        sample_time_to_ros_time(state.last_target_input_stamp)
        if state.last_target_input_stamp is not None
        else RosTime()
    )
    result.last_target_received_stamp = (
        sample_time_to_ros_time(state.last_target_received_stamp)
        if state.last_target_received_stamp is not None
        else RosTime()
    )
    result.command_time_available = state.last_command_sent_stamp is not None
    result.last_command_sent_stamp = (
        sample_time_to_ros_time(state.last_command_sent_stamp)
        if state.last_command_sent_stamp is not None
        else RosTime()
    )
    result.feedback_time_available = state.last_feedback_received_stamp is not None
    result.last_feedback_received_stamp = (
        sample_time_to_ros_time(state.last_feedback_received_stamp)
        if state.last_feedback_received_stamp is not None
        else RosTime()
    )
    result.error_status_time_available = (
        state.last_error_status_received_stamp is not None
    )
    result.last_error_status_received_stamp = (
        sample_time_to_ros_time(state.last_error_status_received_stamp)
        if state.last_error_status_received_stamp is not None
        else RosTime()
    )
    return result


def error_words_to_joint_error(
    side: Side, message: Int16MultiArray, stamp: JointSampleTime
) -> JointError:
    """Convert vendor error words into a validated JointError (0 if absent)."""
    words = list(message.data)
    if len(words) != ACTIVE_JOINT_COUNT:
        raise ValueError(
            f"{side.value} error status must carry {ACTIVE_JOINT_COUNT} words, "
            f"got {len(words)}"
        )
    values = tuple(float(int(word) & 0xFFFF) for word in words)
    return JointError(side=side, values=values, stamp=stamp)


def joint_error_to_error_words(error: JointError) -> list[int]:
    return [int(value) for value in error.values]


def operation_result_to_response(
    result, message: O10ControlState
) -> ControlOperation.Response:
    response = ControlOperation.Response()
    response.success = result.success
    code = result.result_code
    if isinstance(code, ArmCode):
        response.result_code = _wire_constant(
            ControlOperation.Response, "ARM_", code.name
        )
    elif isinstance(code, DisarmCode):
        response.result_code = _wire_constant(
            ControlOperation.Response, "DISARM_", code.name
        )
    elif isinstance(code, ClearFaultCode):
        response.result_code = _wire_constant(
            ControlOperation.Response, "CLEAR_FAULT_", code.name
        )
    else:
        raise TypeError(f"unsupported operation result code: {type(code)!r}")
    response.message = result.message
    response.state = message
    return response


def build_command_message(command) -> JointState:
    """Build a vendor JointState carrying only the hard-limited positions.

    The header retains the ORIGINAL upstream target stamp so downstream stages
    can correlate the command to the soft target that produced it.
    """
    result = JointState()
    result.header.stamp = sample_time_to_ros_time(command.stamp)
    result.position = [float(value) for value in command.values]
    return result


def build_state_message(
    state: ControlStateSnapshot, stamp: RosTime
) -> O10ControlState:
    return control_state_to_message(state, stamp)


def read_response_to_feedback(
    side: Side, response
) -> JointFeedback | None:
    """Convert a successful read response into a validated JointFeedback."""
    if (
        not response.success
        or int(response.result_code)
        != int(ReadO10ActiveJoints.Response.READ_SUCCESS)
    ):
        return None
    try:
        return JointFeedback(
            side=side,
            values=tuple(float(value) for value in response.position),
            stamp=ros_time_to_sample_time(response.sample_stamp),
        )
    except (TypeError, ValueError):
        return None
