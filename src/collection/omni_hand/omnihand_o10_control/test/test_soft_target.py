"""Pure tests for soft-target validation (Spec decision 36; doc 02)."""

from omnihand_o10_contracts import (
    ACTIVE_JOINT_NAMES,
    JointSampleTime,
    Side,
)

from omnihand_o10_control.contracts import (
    ControlConfig,
    SoftTargetValue,
    TargetRejectReason,
)
from omnihand_o10_control.core.soft_target import validate_soft_target

RIGHT_VALID = (0.5, 0.0, 0.4, 0.0, 0.5, 0.5, 0.05, 0.5, 0.05, 0.5)


def _config(**overrides) -> ControlConfig:
    values = dict(
        side=Side.RIGHT,
        max_joint_rates=(0.1,) * 10,
        max_time_credit=0.1,
        slew_compare_epsilon=(1e-6,) * 10,
        target_input_stale_timeout=0.5,
        target_receive_stale_timeout=0.5,
        control_check_period=0.1,
        error_poll_period=0.5,
        error_query_timeout=0.2,
        command_readback_timeout=0.5,
        provider_heartbeat_timeout=1.0,
        init_read_retry_period=0.2,
        init_error_retry_period=0.2,
        read_service_timeout=0.5,
        clear_fault_error_timeout=0.5,
        clear_fault_read_timeout=0.5,
    )
    values.update(overrides)
    return ControlConfig(**values)


def _target(**overrides) -> SoftTargetValue:
    values = dict(
        side=Side.RIGHT,
        name=ACTIVE_JOINT_NAMES,
        position=RIGHT_VALID,
        velocity_empty=True,
        effort_empty=True,
        frame_id="",
        input_stamp=JointSampleTime(0.0),
        received_at=JointSampleTime(0.0),
    )
    values.update(overrides)
    return SoftTargetValue(**values)


def test_valid_target_is_accepted_with_a_validated_value():
    value = _target()
    target, reason, message = validate_soft_target(value, _config())
    assert reason is TargetRejectReason.OK
    assert target is not None
    assert list(target.values) == list(RIGHT_VALID)
    assert target.stamp.seconds == 0.0


def test_side_mismatch_is_rejected_as_name():
    value = _target(side=Side.LEFT)
    _, reason, _ = validate_soft_target(value, _config())
    assert reason is TargetRejectReason.REJECT_NAME


def test_wrong_name_order_is_rejected():
    value = _target(name=tuple(reversed(ACTIVE_JOINT_NAMES)))
    _, reason, _ = validate_soft_target(value, _config())
    assert reason is TargetRejectReason.REJECT_NAME


def test_wrong_position_dimension_is_rejected():
    value = _target(position=RIGHT_VALID[:9])
    _, reason, _ = validate_soft_target(value, _config())
    assert reason is TargetRejectReason.REJECT_POSITION


def test_non_finite_position_is_rejected():
    import math

    value = _target(position=(float("nan"),) + RIGHT_VALID[1:])
    _, reason, _ = validate_soft_target(value, _config())
    assert reason is TargetRejectReason.REJECT_NONFINITE


def test_side_limit_violation_is_rejected():
    # right thumb_abad upper limit is 0.05
    value = _target(position=(0.5, 0.5) + RIGHT_VALID[2:])
    _, reason, _ = validate_soft_target(value, _config())
    assert reason is TargetRejectReason.REJECT_SIDE_LIMIT


def test_nonempty_velocity_or_effort_is_rejected():
    _, reason, _ = validate_soft_target(
        _target(velocity_empty=False), _config()
    )
    assert reason is TargetRejectReason.REJECT_NONEMPTY_VELOCITY_EFFORT
    _, reason, _ = validate_soft_target(_target(effort_empty=False), _config())
    assert reason is TargetRejectReason.REJECT_NONEMPTY_VELOCITY_EFFORT


def test_nonempty_frame_id_is_rejected():
    _, reason, _ = validate_soft_target(_target(frame_id="base"), _config())
    assert reason is TargetRejectReason.REJECT_HEADER


def test_missing_input_stamp_is_rejected():
    _, reason, _ = validate_soft_target(_target(input_stamp=None), _config())
    assert reason is TargetRejectReason.REJECT_HEADER


def test_future_stamp_is_rejected_as_stale():
    _, reason, _ = validate_soft_target(
        _target(input_stamp=JointSampleTime(1.0), received_at=JointSampleTime(0.5)),
        _config(),
    )
    assert reason is TargetRejectReason.REJECT_STALE


def test_expired_stamp_is_rejected_as_stale():
    _, reason, _ = validate_soft_target(
        _target(input_stamp=JointSampleTime(0.0), received_at=JointSampleTime(1.0)),
        _config(target_input_stale_timeout=0.5),
    )
    assert reason is TargetRejectReason.REJECT_STALE


def test_stamp_within_timeout_is_accepted():
    target, reason, _ = validate_soft_target(
        _target(input_stamp=JointSampleTime(0.0), received_at=JointSampleTime(0.4)),
        _config(target_input_stale_timeout=0.5),
    )
    assert reason is TargetRejectReason.OK
    assert target is not None
