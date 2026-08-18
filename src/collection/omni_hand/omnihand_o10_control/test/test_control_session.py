"""State-machine tests for the per-side control session (ADR-0008, A03)."""

import pytest
from omnihand_o10_contracts import (
    ACTIVE_JOINT_NAMES,
    JointError,
    JointFeedback,
    JointSampleTime,
    Side,
)

from omnihand_o10_control.application.control_session import ControlSession
from omnihand_o10_control.contracts import (
    ArmCode,
    ClearFaultCode,
    CommandPublishFailed,
    CommandSent,
    ControlConfig,
    DisarmCode,
    ErrorStatusReceived,
    FaultReason,
    FeedbackReceived,
    InvalidErrorStatusReceived,
    InvalidFeedbackReceived,
    OperatorArmRequest,
    OperatorClearFaultRequest,
    OperatorDisarmRequest,
    OperationResult,
    Phase,
    PublishControlState,
    QueryErrorStatus,
    ReadActiveJointsResult,
    ReadActiveJointsTimeout,
    RequestActiveJointsRead,
    SendJointCommand,
    SoftTargetValue,
    TargetReceived,
    TargetRejectReason,
    TimeoutCheck,
    Trigger,
)

RIGHT_VALID = (0.5, 0.0, 0.4, 0.0, 0.5, 0.5, 0.05, 0.5, 0.05, 0.5)


def make_config(**overrides) -> ControlConfig:
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


def feedback(pos=(0.0,) * 10, stamp=0.0) -> JointFeedback:
    return JointFeedback(Side.RIGHT, pos, JointSampleTime(stamp))


def error_status(bits=(0.0,) * 10, stamp=0.0) -> JointError:
    return JointError(Side.RIGHT, bits, JointSampleTime(stamp))


def soft_target(position=RIGHT_VALID, stamp=2.0) -> SoftTargetValue:
    return SoftTargetValue(
        Side.RIGHT,
        ACTIVE_JOINT_NAMES,
        position,
        True,
        True,
        "",
        JointSampleTime(stamp),
        JointSampleTime(stamp),
    )


def init_session(session: ControlSession) -> None:
    """Give a session a valid feedback read + a healthy error monitor."""
    session.on_read_result(
        ReadActiveJointsResult(
            True, feedback(), JointSampleTime(0.0), 0.0
        )
    )
    session.on_error_status(
        ErrorStatusReceived(error_status(), JointSampleTime(1.0), 1.0)
    )


def deliver_target(session: ControlSession, stamp=2.0, now=2.0):
    value = soft_target(stamp=stamp)
    session.on_target(
        TargetReceived(value, JointSampleTime(now), now, JointSampleTime(now))
    )


def single_result(effects):
    results = [e for e in effects if isinstance(e, OperationResult)]
    assert len(results) == 1
    return results[0]


def test_initial_phase_is_uninitialized():
    session = ControlSession(make_config())
    snapshot = session.initial_snapshot(JointSampleTime(0.0))
    assert snapshot.phase is Phase.UNINITIALIZED
    assert not snapshot.armed
    assert not snapshot.fault_latched
    assert not snapshot.motion_enabled


def test_first_feedback_read_transitions_to_disarmed():
    session = ControlSession(make_config())
    effects = session.on_read_result(
        ReadActiveJointsResult(
            True, feedback(), JointSampleTime(0.0), 0.0
        )
    )
    assert len(effects) == 1
    assert isinstance(effects[0], PublishControlState)
    snapshot = session.initial_snapshot(JointSampleTime(0.0))
    assert snapshot.phase is Phase.INITIALIZING
    assert snapshot.feedback_ready


def test_arm_rejects_before_feedback_read():
    session = ControlSession(make_config())
    result = single_result(
        session.on_arm_request(OperatorArmRequest(1.0, JointSampleTime(1.0)))
    )
    assert not result.success
    assert result.result_code == ArmCode.REJECTED_FEEDBACK_NOT_READY


def test_arm_rejects_without_error_monitor():
    session = ControlSession(make_config())
    session.on_read_result(
        ReadActiveJointsResult(
            True, feedback(), JointSampleTime(0.0), 0.0
        )
    )
    deliver_target(session)
    result = single_result(
        session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    )
    assert result.result_code == ArmCode.REJECTED_ERROR_MONITOR_NOT_READY


def test_arm_rejects_without_a_valid_target():
    session = ControlSession(make_config())
    init_session(session)
    result = single_result(
        session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    )
    assert result.result_code == ArmCode.REJECTED_TARGET_NOT_READY


def test_arm_rejects_a_stale_target():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session, stamp=1.0, now=2.0)  # age 1.0s > 0.5s timeout
    result = single_result(
        session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    )
    assert result.result_code == ArmCode.REJECTED_TARGET_STALE


def test_arm_succeeds_and_enables_motion():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    result = single_result(
        session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    )
    assert result.success
    assert result.result_code == ArmCode.SUCCESS
    assert result.state.phase is Phase.ACTIVE
    assert result.state.armed
    assert result.state.motion_enabled


def test_disarmed_target_never_produces_a_command():
    session = ControlSession(make_config())
    init_session(session)
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.0), 2.0, JointSampleTime(2.0))
    )
    assert not any(isinstance(e, SendJointCommand) for e in effects)


def test_armed_target_produces_a_slew_limited_command():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.01), 2.01, JointSampleTime(2.01))
    )
    commands = [e for e in effects if isinstance(e, SendJointCommand)]
    assert len(commands) == 1
    # step = rate * credit = 0.1 * 0.01
    assert list(commands[0].command.values)[0] == pytest.approx(0.001)


def test_command_sent_confirms_and_advances_the_slew_base():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.01), 2.01, JointSampleTime(2.01))
    )
    command = effects[0].command
    confirm = session.on_command_sent(
        CommandSent(command, JointSampleTime(2.01), 2.01)
    )
    assert isinstance(confirm[0], PublishControlState)
    assert confirm[0].state.command_published
    # next target now steps from the confirmed base, not the soft target
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.02), 2.02, JointSampleTime(2.02))
    )
    assert list(effects[0].command.values)[0] == pytest.approx(0.002)


def test_publish_failure_does_not_advance_the_slew_base():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.01), 2.01, JointSampleTime(2.01))
    )
    failed = session.on_command_publish_failed(
        CommandPublishFailed(JointSampleTime(2.01), 2.01)
    )
    assert isinstance(failed[0], PublishControlState)
    assert not failed[0].state.command_published
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.02), 2.02, JointSampleTime(2.02))
    )
    # base never advanced past 0.0; clock kept running (step = 0.1 * 0.02)
    assert list(effects[0].command.values)[0] == pytest.approx(0.002)


def test_command_readback_timeout_latches_a_fault():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.01), 2.01, JointSampleTime(2.01))
    )
    session.on_command_sent(CommandSent(effects[0].command, JointSampleTime(2.01), 2.01))
    timeouts = session.check_timeouts(TimeoutCheck(3.0, JointSampleTime(3.0)))
    fault_states = [e.state for e in timeouts if isinstance(e, PublishControlState)]
    assert fault_states
    assert fault_states[0].phase is Phase.FAULT
    assert fault_states[0].fault_latched
    assert FaultReason.COMMAND_READBACK_TIMEOUT in fault_states[0].fault_reasons


def test_provider_heartbeat_timeout_latches_a_restart_fault():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    timeouts = session.check_timeouts(TimeoutCheck(4.0, JointSampleTime(4.0)))
    fault_states = [e.state for e in timeouts if isinstance(e, PublishControlState)]
    assert FaultReason.RESTART_DISCONNECT in fault_states[0].fault_reasons


def test_vendor_error_bit_latches_a_fault():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_error_status(
        ErrorStatusReceived(error_status(bits=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)), JointSampleTime(2.5), 2.5)
    )
    states = [e.state for e in effects if isinstance(e, PublishControlState)]
    assert states[0].phase is Phase.FAULT
    assert FaultReason.VENDOR_ERROR_BIT in states[0].fault_reasons
    assert not states[0].motion_enabled


def test_commu_except_bit_alone_does_not_latch_a_fault():
    # bit4 (0x10) is the vendor's HISTORICAL communication marker; per the
    # official Agilink SDK it does not stop vendor-side control, so it must
    # not latch a HARDWARE_ERROR fault (ADR-0005 amendment).
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_error_status(
        ErrorStatusReceived(error_status(bits=(16.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)), JointSampleTime(2.5), 2.5)
    )
    states = [e.state for e in effects if isinstance(e, PublishControlState)]
    assert states and not states[0].fault_latched
    assert FaultReason.HARDWARE_ERROR not in states[0].fault_reasons


def test_commu_except_bit_with_fatal_bit_still_latches_a_fault():
    # commu_except (bit4) is masked, but a real fatal bit (bit0 = stalled)
    # on the same or another joint must still latch a HARDWARE_ERROR fault.
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    effects = session.on_error_status(
        ErrorStatusReceived(error_status(bits=(17.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)), JointSampleTime(2.5), 2.5)
    )
    states = [e.state for e in effects if isinstance(e, PublishControlState)]
    assert states[0].phase is Phase.FAULT
    assert FaultReason.VENDOR_ERROR_BIT in states[0].fault_reasons
    assert not states[0].motion_enabled


def test_illegal_feedback_latches_a_fault():
    session = ControlSession(make_config())
    init_session(session)
    effects = session.on_invalid_feedback(
        InvalidFeedbackReceived(Side.RIGHT, "non-finite", JointSampleTime(2.0), 2.0)
    )
    states = [e.state for e in effects if isinstance(e, PublishControlState)]
    assert FaultReason.ILLEGAL_FEEDBACK in states[0].fault_reasons


def test_error_monitor_query_timeout_latches_after_ready():
    session = ControlSession(make_config())
    init_session(session)
    # force an in-flight error query
    session.check_timeouts(TimeoutCheck(1.1, JointSampleTime(1.1)))
    timeouts = session.check_timeouts(TimeoutCheck(1.6, JointSampleTime(1.6)))
    states = [e.state for e in timeouts if isinstance(e, PublishControlState)]
    assert states and FaultReason.ERROR_MONITOR_TIMEOUT in states[0].fault_reasons


def test_invalid_error_status_latches_after_monitor_was_ready():
    session = ControlSession(make_config())
    init_session(session)
    effects = session.on_invalid_error_status(
        InvalidErrorStatusReceived(Side.RIGHT, "bad words", JointSampleTime(2.0), 2.0)
    )
    states = [e.state for e in effects if isinstance(e, PublishControlState)]
    assert states and FaultReason.ERROR_MONITOR_TIMEOUT in states[0].fault_reasons


def test_disarm_succeeds_and_disables_motion():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    result = single_result(
        session.on_disarm_request(OperatorDisarmRequest(3.0, JointSampleTime(3.0)))
    )
    assert result.success
    assert result.result_code == DisarmCode.SUCCESS
    assert result.state.phase is Phase.DISARMED_READY
    assert not result.state.armed


def latch_fault(session: ControlSession) -> None:
    """Latch a fault and keep the provider heartbeat alive afterwards."""
    session.on_invalid_feedback(
        InvalidFeedbackReceived(Side.RIGHT, "non-finite", JointSampleTime(2.0), 2.0)
    )
    session.on_error_status(
        ErrorStatusReceived(error_status(), JointSampleTime(2.6), 2.6)
    )


def test_disarm_succeeds_in_fault_and_preserves_fault():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    result = single_result(
        session.on_disarm_request(OperatorDisarmRequest(3.0, JointSampleTime(3.0)))
    )
    assert result.success
    assert result.result_code == DisarmCode.ALREADY_DISARMED
    assert result.state.fault_latched


def test_clear_fault_success_path():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    start = session.on_clear_fault_request(
        OperatorClearFaultRequest(3.0, JointSampleTime(3.0))
    )
    assert isinstance(start[0], QueryErrorStatus)
    read_effects = session.on_clear_fault_error_query(True, (0,) * 10, 3.01, JointSampleTime(3.01))
    assert isinstance(read_effects[0], RequestActiveJointsRead)
    done = session.on_clear_fault_read(True, feedback(), 3.02, JointSampleTime(3.02))
    result = single_result(done)
    assert result.success
    assert result.result_code == ClearFaultCode.SUCCESS
    assert result.state.phase is Phase.DISARMED_READY
    assert not result.state.fault_latched


def test_clear_fault_rejects_hardware_error_present():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    done = session.on_clear_fault_error_query(True, (1, 0, 0, 0, 0, 0, 0, 0, 0, 0), 3.01, JointSampleTime(3.01))
    result = single_result(done)
    assert result.result_code == ClearFaultCode.REJECTED_HARDWARE_ERROR_PRESENT


def test_clear_fault_ignores_commu_except_bit():
    # commu_except (bit4 = 16) is a vendor-historical marker and must not
    # block clear_fault: with only bit4 set, clear_fault proceeds to the
    # active-joint read stage instead of rejecting (ADR-0005 amendment).
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    done = session.on_clear_fault_error_query(
        True, (16, 0, 0, 0, 0, 0, 0, 0, 0, 0), 3.01, JointSampleTime(3.01)
    )
    effects = done
    read_requests = [e for e in effects if isinstance(e, RequestActiveJointsRead)]
    assert read_requests, "expected clear_fault to proceed to the read stage"
    assert not [e for e in effects if isinstance(e, OperationResult)]


def test_clear_fault_rejects_error_query_timeout():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    done = session.on_clear_fault_error_query(False, None, 3.01, JointSampleTime(3.01))
    result = single_result(done)
    assert result.result_code == ClearFaultCode.REJECTED_ERROR_QUERY_TIMEOUT


def test_clear_fault_rejects_invalid_error_status():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    done = session.on_clear_fault_error_query(True, None, 3.01, JointSampleTime(3.01))
    result = single_result(done)
    assert result.result_code == ClearFaultCode.REJECTED_ERROR_STATUS_INVALID


def test_clear_fault_rejects_feedback_read_timeout():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    session.on_clear_fault_error_query(True, (0,) * 10, 3.01, JointSampleTime(3.01))
    done = session.on_clear_fault_read(False, None, 3.02, JointSampleTime(3.02))
    result = single_result(done)
    assert result.result_code == ClearFaultCode.REJECTED_FEEDBACK_READ_TIMEOUT


def test_clear_fault_rejects_invalid_feedback():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    session.on_clear_fault_error_query(True, (0,) * 10, 3.01, JointSampleTime(3.01))
    done = session.on_clear_fault_read(True, None, 3.02, JointSampleTime(3.02))
    result = single_result(done)
    assert result.result_code == ClearFaultCode.REJECTED_FEEDBACK_INVALID


def test_clear_fault_on_healthy_side_is_already_clear():
    session = ControlSession(make_config())
    init_session(session)
    result = single_result(
        session.on_clear_fault_request(OperatorClearFaultRequest(2.0, JointSampleTime(2.0)))
    )
    assert result.result_code == ClearFaultCode.ALREADY_CLEAR


def test_rejected_target_stops_motion_and_records_reason():
    session = ControlSession(make_config())
    init_session(session)
    deliver_target(session)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    bad = soft_target(position=(0.5, 0.5) + RIGHT_VALID[2:])  # out of limits
    effects = session.on_target(
        TargetReceived(bad, JointSampleTime(2.1), 2.1, JointSampleTime(2.1))
    )
    states = [e.state for e in effects if isinstance(e, PublishControlState)]
    assert states[0].target_result is TargetRejectReason.REJECT_SIDE_LIMIT
    assert states[0].motion_enabled
    # a later valid target restores motion
    effects = session.on_target(
        TargetReceived(soft_target(), JointSampleTime(2.2), 2.2, JointSampleTime(2.2))
    )
    assert any(isinstance(e, SendJointCommand) for e in effects)


def test_target_staleness_turns_motion_off_without_a_fault():
    session = ControlSession(
        make_config(provider_heartbeat_timeout=100.0)
    )
    init_session(session)
    deliver_target(session, stamp=2.0, now=2.0)
    session.on_arm_request(OperatorArmRequest(2.0, JointSampleTime(2.0)))
    # advance time well past both target freshness limits
    timeouts = session.check_timeouts(TimeoutCheck(5.0, JointSampleTime(5.0)))
    states = [e.state for e in timeouts if isinstance(e, PublishControlState)]
    assert len(states) == 1
    assert not states[0].target_fresh
    assert not states[0].motion_enabled
    assert not states[0].fault_latched
    # a fresh target restores motion without a fault
    effects = session.on_target(
        TargetReceived(soft_target(stamp=5.0), JointSampleTime(5.1), 5.1, JointSampleTime(5.1))
    )
    assert any(isinstance(e, SendJointCommand) for e in effects)


def test_init_read_retry_is_issued_until_feedback_ready():
    session = ControlSession(make_config())
    effects = session.check_timeouts(TimeoutCheck(0.3, JointSampleTime(0.3)))
    assert any(isinstance(e, RequestActiveJointsRead) for e in effects)
    effects = session.check_timeouts(TimeoutCheck(0.31, JointSampleTime(0.31)))
    # still in flight; no duplicate read request
    assert not any(isinstance(e, RequestActiveJointsRead) for e in effects)
    session.on_read_timeout(ReadActiveJointsTimeout(0.31))
    effects = session.check_timeouts(TimeoutCheck(0.6, JointSampleTime(0.6)))
    assert any(isinstance(e, RequestActiveJointsRead) for e in effects)


def test_error_poll_is_issued_periodically_when_ready():
    session = ControlSession(make_config())
    init_session(session)
    effects = session.check_timeouts(TimeoutCheck(1.1, JointSampleTime(1.1)))
    assert any(isinstance(e, QueryErrorStatus) for e in effects)
    effects = session.check_timeouts(TimeoutCheck(1.11, JointSampleTime(1.11)))
    assert not any(isinstance(e, QueryErrorStatus) for e in effects)


def test_timeouts_are_suspended_during_clear_fault():
    session = ControlSession(make_config())
    init_session(session)
    latch_fault(session)
    session.on_clear_fault_request(OperatorClearFaultRequest(3.0, JointSampleTime(3.0)))
    effects = session.check_timeouts(TimeoutCheck(30.0, JointSampleTime(30.0)))
    assert effects == []
