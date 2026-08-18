"""Schema and generated-interface smoke tests for the ROS wire package."""


def _fields(message_type):
    return message_type._fields_and_field_types


def test_raw_hand_frame_schema():
    from geometry_msgs.msg import Point, Quaternion
    from rokoko_omnihand_msgs.msg import RawHandFrame

    assert _fields(RawHandFrame) == {
        "header": "std_msgs/Header",
        "actor_index": "uint32",
        "actor_name": "string",
        "source_timestamp": "double",
        "node_names": "string[21]",
        "positions": "geometry_msgs/Point[21]",
        "orientations": "geometry_msgs/Quaternion[21]",
    }
    msg = RawHandFrame()
    assert len(msg.node_names) == len(msg.positions) == len(msg.orientations) == 21
    assert isinstance(msg.positions[0], Point)
    assert isinstance(msg.orientations[0], Quaternion)
    assert "side" not in _fields(RawHandFrame)


def test_read_o10_active_joints_schema_and_values():
    from builtin_interfaces.msg import Time
    from rokoko_omnihand_msgs.srv import ReadO10ActiveJoints

    assert _fields(ReadO10ActiveJoints.Request) == {}
    assert _fields(ReadO10ActiveJoints.Response) == {
        "success": "boolean",
        "result_code": "uint8",
        "message": "string",
        "sample_stamp": "builtin_interfaces/Time",
        "position": "double[10]",
    }
    response = ReadO10ActiveJoints.Response()
    assert isinstance(response.sample_stamp, Time)
    assert len(response.position) == 10
    assert {
        name: getattr(ReadO10ActiveJoints.Response, name)
        for name in (
            "READ_SUCCESS",
            "READ_DEVICE_UNAVAILABLE",
            "READ_HARDWARE_ERROR",
            "READ_INVALID_RESULT",
            "READ_INTERNAL_ERROR",
        )
    } == {
        "READ_SUCCESS": 0,
        "READ_DEVICE_UNAVAILABLE": 1,
        "READ_HARDWARE_ERROR": 2,
        "READ_INVALID_RESULT": 3,
        "READ_INTERNAL_ERROR": 4,
    }


def test_retargeting_state_is_flat_doc05_schema():
    from rokoko_omnihand_msgs.msg import RetargetingState

    assert _fields(RetargetingState) == {
        "header": "std_msgs/Header",
        "side": "string",
        "input_stamp": "builtin_interfaces/Time",
        "solve_executed": "boolean",
        "solve_finished_stamp": "builtin_interfaces/Time",
        "solve_duration_sec": "double",
        "phase": "uint8",
        "ready": "boolean",
        "stale": "boolean",
        "command_published": "boolean",
        "length_state": "uint8[5]",
        "ik_state": "uint8[5]",
        "has_valid_ik": "boolean[5]",
        "used_previous_valid_target": "boolean[5]",
        "residual_available": "boolean[5]",
        "normalized_residual": "double[5]",
        "target_projection_applied": "boolean[5]",
        "target_projection_distance_available": "boolean[5]",
        "normalized_target_projection_distance": "double[5]",
        "solver_result_code": "int32[5]",
        "solver_evaluations": "uint32[5]",
        "recovery_valid_count": "uint32",
        "recovery_valid_duration_sec": "double",
    }
    assert not hasattr(RetargetingState(), "fingers")
    assert not hasattr(RetargetingState, "PHASE_FROZEN")
    assert RetargetingState.SOLVER_NOT_RUN == 0
    assert {
        name: getattr(RetargetingState, name)
        for name in (
            "PHASE_INITIALIZING",
            "PHASE_COLLECTING_LENGTHS",
            "PHASE_WAITING_FIRST_VALID_IK",
            "PHASE_TRACKING",
            "PHASE_STALE",
            "PHASE_RECOVERY_CONFIRMING",
            "PHASE_RECOVERY_RESUMING",
            "PHASE_MODEL_ERROR",
        )
    } == {
        "PHASE_INITIALIZING": 0,
        "PHASE_COLLECTING_LENGTHS": 1,
        "PHASE_WAITING_FIRST_VALID_IK": 2,
        "PHASE_TRACKING": 3,
        "PHASE_STALE": 4,
        "PHASE_RECOVERY_CONFIRMING": 5,
        "PHASE_RECOVERY_RESUMING": 6,
        "PHASE_MODEL_ERROR": 7,
    }
    assert {
        name: getattr(RetargetingState, name)
        for name in (
            "LENGTH_COLLECTING",
            "LENGTH_FROZEN",
            "LENGTH_CURRENT_INVALID",
            "IK_UNINITIALIZED",
            "IK_VALID",
            "IK_INPUT_INVALID",
            "IK_SIDE_INVALID",
            "IK_RESIDUAL_EXCEEDED",
            "IK_SOLVER_ERROR",
            "IK_NOT_RUN_LENGTH_COLLECTING",
            "IK_NOT_RUN_STALE",
        )
    } == {
        "LENGTH_COLLECTING": 0,
        "LENGTH_FROZEN": 1,
        "LENGTH_CURRENT_INVALID": 2,
        "IK_UNINITIALIZED": 0,
        "IK_VALID": 1,
        "IK_INPUT_INVALID": 2,
        "IK_SIDE_INVALID": 3,
        "IK_RESIDUAL_EXCEEDED": 4,
        "IK_SOLVER_ERROR": 5,
        "IK_NOT_RUN_LENGTH_COLLECTING": 6,
        "IK_NOT_RUN_STALE": 7,
    }


def test_o10_control_state_is_exact_doc06_schema():
    from rokoko_omnihand_msgs.msg import O10ControlState

    assert _fields(O10ControlState) == {
        "header": "std_msgs/Header",
        "side": "string",
        "event": "uint8",
        "phase": "uint8",
        "feedback_ready": "boolean",
        "error_monitor_ready": "boolean",
        "target_ready": "boolean",
        "target_fresh": "boolean",
        "armed": "boolean",
        "fault_latched": "boolean",
        "motion_enabled": "boolean",
        "target_result": "uint8",
        "command_published": "boolean",
        "slew_limited": "boolean[10]",
        "fault_reason_mask": "uint32",
        "hardware_error_bits": "uint16[10]",
        "target_time_available": "boolean",
        "last_target_input_stamp": "builtin_interfaces/Time",
        "last_target_received_stamp": "builtin_interfaces/Time",
        "command_time_available": "boolean",
        "last_command_sent_stamp": "builtin_interfaces/Time",
        "feedback_time_available": "boolean",
        "last_feedback_received_stamp": "builtin_interfaces/Time",
        "error_status_time_available": "boolean",
        "last_error_status_received_stamp": "builtin_interfaces/Time",
    }
    msg = O10ControlState()
    assert len(msg.slew_limited) == len(msg.hardware_error_bits) == 10
    assert {
        name: getattr(O10ControlState, name)
        for name in (
            "EVENT_STARTUP",
            "EVENT_TARGET_PROCESSED",
            "EVENT_TARGET_TIMEOUT",
            "EVENT_FEEDBACK_RECEIVED",
            "EVENT_ERROR_STATUS_RECEIVED",
            "EVENT_OPERATOR_REQUEST",
            "EVENT_FAULT_CHANGED",
            "EVENT_COMPONENT_STATE_CHANGED",
        )
    } == {
        "EVENT_STARTUP": 0,
        "EVENT_TARGET_PROCESSED": 1,
        "EVENT_TARGET_TIMEOUT": 2,
        "EVENT_FEEDBACK_RECEIVED": 3,
        "EVENT_ERROR_STATUS_RECEIVED": 4,
        "EVENT_OPERATOR_REQUEST": 5,
        "EVENT_FAULT_CHANGED": 6,
        "EVENT_COMPONENT_STATE_CHANGED": 7,
    }
    assert {
        name: getattr(O10ControlState, name)
        for name in (
            "PHASE_INITIALIZING",
            "PHASE_DISARMED_NOT_READY",
            "PHASE_DISARMED_READY",
            "PHASE_ACTIVE",
            "PHASE_PAUSED_TARGET_STALE",
            "PHASE_FAULT_LATCHED",
        )
    } == {
        "PHASE_INITIALIZING": 0,
        "PHASE_DISARMED_NOT_READY": 1,
        "PHASE_DISARMED_READY": 2,
        "PHASE_ACTIVE": 3,
        "PHASE_PAUSED_TARGET_STALE": 4,
        "PHASE_FAULT_LATCHED": 5,
    }
    assert {
        name: getattr(O10ControlState, name)
        for name in (
            "TARGET_NOT_EVALUATED",
            "TARGET_SENT",
            "TARGET_VALID_MOTION_DISABLED",
            "TARGET_REJECTED_SCHEMA",
            "TARGET_REJECTED_NAME_ORDER",
            "TARGET_REJECTED_NONFINITE",
            "TARGET_REJECTED_LIMIT",
            "TARGET_REJECTED_AUX_FIELDS",
            "TARGET_REJECTED_TIMESTAMP",
            "TARGET_REJECTED_CONTROL_STATE",
        )
    } == {
        "TARGET_NOT_EVALUATED": 0,
        "TARGET_SENT": 1,
        "TARGET_VALID_MOTION_DISABLED": 2,
        "TARGET_REJECTED_SCHEMA": 3,
        "TARGET_REJECTED_NAME_ORDER": 4,
        "TARGET_REJECTED_NONFINITE": 5,
        "TARGET_REJECTED_LIMIT": 6,
        "TARGET_REJECTED_AUX_FIELDS": 7,
        "TARGET_REJECTED_TIMESTAMP": 8,
        "TARGET_REJECTED_CONTROL_STATE": 9,
    }
    assert {
        name: getattr(O10ControlState, name)
        for name in (
            "FAULT_HARDWARE_ERROR",
            "FAULT_COMMAND_READBACK_TIMEOUT",
            "FAULT_INVALID_FEEDBACK",
            "FAULT_SAFETY_INVARIANT",
            "FAULT_COMPONENT_RESTART_OR_DISCONNECT",
            "FAULT_ERROR_MONITOR_TIMEOUT",
        )
    } == {
        "FAULT_HARDWARE_ERROR": 1,
        "FAULT_COMMAND_READBACK_TIMEOUT": 2,
        "FAULT_INVALID_FEEDBACK": 4,
        "FAULT_SAFETY_INVARIANT": 8,
        "FAULT_COMPONENT_RESTART_OR_DISCONNECT": 16,
        "FAULT_ERROR_MONITOR_TIMEOUT": 32,
    }


def test_control_operation_has_all_doc07_result_codes_and_snapshot():
    from rokoko_omnihand_msgs.msg import O10ControlState
    from rokoko_omnihand_msgs.srv import ControlOperation

    assert _fields(ControlOperation.Request) == {}
    assert _fields(ControlOperation.Response) == {
        "success": "boolean",
        "result_code": "uint8",
        "message": "string",
        "state": "rokoko_omnihand_msgs/O10ControlState",
    }
    assert isinstance(ControlOperation.Response().state, O10ControlState)
    expected = {
        "ARM_SUCCESS": 0,
        "ARM_ALREADY_ARMED": 1,
        "ARM_REJECTED_FAULT_LATCHED": 10,
        "ARM_REJECTED_FEEDBACK_NOT_READY": 11,
        "ARM_REJECTED_ERROR_MONITOR_NOT_READY": 12,
        "ARM_REJECTED_TARGET_NOT_READY": 13,
        "ARM_REJECTED_TARGET_STALE": 14,
        "ARM_REJECTED_CONTROL_STATE": 15,
        "DISARM_SUCCESS": 20,
        "DISARM_ALREADY_DISARMED": 21,
        "DISARM_REJECTED_CONTROL_STATE": 22,
        "CLEAR_FAULT_SUCCESS": 30,
        "CLEAR_FAULT_ALREADY_CLEAR": 31,
        "CLEAR_FAULT_REJECTED_CONTROL_STATE": 40,
        "CLEAR_FAULT_REJECTED_COMMUNICATION_UNHEALTHY": 41,
        "CLEAR_FAULT_REJECTED_ERROR_QUERY_TIMEOUT": 42,
        "CLEAR_FAULT_REJECTED_ERROR_STATUS_INVALID": 43,
        "CLEAR_FAULT_REJECTED_HARDWARE_ERROR_PRESENT": 44,
        "CLEAR_FAULT_REJECTED_FEEDBACK_READ_TIMEOUT": 45,
        "CLEAR_FAULT_REJECTED_FEEDBACK_INVALID": 46,
        "CLEAR_FAULT_REJECTED_LIMITER_INIT_FAILED": 47,
    }
    assert {name: getattr(ControlOperation.Response, name) for name in expected} == expected
