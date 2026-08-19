"""Pure per-side O10 control state machine.

The aggregate consumes pure events and returns pure effects.  The ROS node is
the only effect executor and must feed successful effects back as events.
"""

from __future__ import annotations

import threading

from omnihand_o10_contracts import ACTIVE_JOINT_COUNT, JointFeedback, JointTarget

from ..contracts import (
    ClearFaultCode,
    CommandPublishFailed,
    CommandSent,
    ControlConfig,
    ControlStateSnapshot,
    Effect,
    ErrorStatusReceived,
    FATAL_ERROR_BIT_MASK,
    FaultReason,
    FeedbackReceived,
    InvalidErrorStatusReceived,
    InvalidFeedbackReceived,
    OperationResult,
    OperatorClearFaultRequest,
    Phase,
    PublishControlState,
    QueryErrorStatus,
    ReadActiveJointsResult,
    ReadActiveJointsTimeout,
    RequestActiveJointsRead,
    SendJointCommand,
    TargetReceived,
    TargetRejectReason,
    TargetResult,
    TimeoutCheck,
    Trigger,
)
from ..core.slew_limiter import (
    SlewLimiter,
    SlewResultError,
    SlewTimeError,
    SlewUnavailableError,
)
from ..core.soft_target import validate_soft_target

__all__ = ["ControlSession"]


class ControlSession:
    """One independently locked, per-side O10 control aggregate."""

    def __init__(self, config: ControlConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._phase = Phase.INITIALIZING
        self._fault_latched = False
        self._fault_reasons: set[FaultReason] = set()
        self._feedback_ready = False
        self._error_monitor_ready = False
        self._last_error = None
        self._last_error_received: float | None = None
        self._last_error_status_received_stamp = None
        self._hardware_error_bits = (0,) * ACTIVE_JOINT_COUNT
        self._target_ready = False
        self._last_target: JointTarget | None = None
        self._last_target_input_stamp = None
        self._last_target_received_stamp = None
        self._last_target_received_monotonic: float | None = None
        self._target_result = TargetResult.NOT_EVALUATED
        self._last_feedback_received_stamp = None
        self._last_command_sent_stamp = None
        self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
        self._command_published = False
        self._command_pending = False
        self._last_command_monotonic: float | None = None
        self._last_heartbeat: float | None = None
        self._last_read_request = 0.0
        self._read_in_flight = False
        self._last_error_query = 0.0
        self._error_query_in_flight = False
        self._error_query_deadline = 0.0
        self._clear_fault_state = "idle"
        self._last_published_target_fresh = False
        self._last_monotonic_observed = 0.0
        self._limiter = SlewLimiter(
            config.side, config.max_joint_rates, config.max_time_credit
        )

    def initial_snapshot(self, ros_now) -> ControlStateSnapshot:
        with self._lock:
            return self._snapshot(Trigger.STARTUP, ros_now)

    @property
    def clear_fault_in_progress(self) -> bool:
        with self._lock:
            return self._clear_fault_state != "idle"

    def on_target(self, event: TargetReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            return self._on_target(event)

    def on_feedback(self, event: FeedbackReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            return self._on_feedback(event)

    def on_invalid_feedback(self, event: InvalidFeedbackReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            return self._latch_fault(
                FaultReason.INVALID_FEEDBACK, event.received_at, event.monotonic_now
            )

    def on_error_status(self, event: ErrorStatusReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._last_error = event.error
            self._last_error_received = event.monotonic_now
            self._last_error_status_received_stamp = event.received_at
            self._hardware_error_bits = tuple(int(value) for value in event.error.values)
            self._last_heartbeat = event.monotonic_now
            self._error_query_in_flight = False
            self._error_monitor_ready = True
            # The vendor's commu_except bit (bit4) records HISTORICAL
            # communication issues and, per the official Agilink SDK, does not
            # stop vendor-side control. Only the remaining fatal bits
            # (stalled / overheat / over_current / motor_except) latch a
            # HARDWARE_ERROR control fault.
            if any(
                int(value) & FATAL_ERROR_BIT_MASK != 0
                for value in event.error.values
            ):
                return self._latch_fault(
                    FaultReason.HARDWARE_ERROR,
                    event.received_at,
                    event.monotonic_now,
                )
            return self._publish(Trigger.ERROR_STATUS_RECEIVED, event.received_at)

    def on_invalid_error_status(self, event: InvalidErrorStatusReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._error_query_in_flight = False
            if self._error_monitor_ready:
                return self._latch_fault(
                    FaultReason.ERROR_MONITOR_TIMEOUT,
                    event.received_at,
                    event.monotonic_now,
                )
            return []

    def on_read_result(self, event: ReadActiveJointsResult) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._read_in_flight = False
            if not event.success or event.feedback is None:
                return []
            self._last_heartbeat = event.monotonic_now
            try:
                self._adopt_feedback(
                    event.feedback, event.received_at, event.monotonic_now
                )
            except ValueError:
                return self._latch_fault(
                    FaultReason.INVALID_FEEDBACK,
                    event.received_at,
                    event.monotonic_now,
                )
            return self._publish(Trigger.FEEDBACK_RECEIVED, event.received_at)

    def on_read_timeout(self, event: ReadActiveJointsTimeout) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._read_in_flight = False
            return []

    def on_command_sent(self, event: CommandSent) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            try:
                self._limiter.confirm(event.command.values, event.monotonic_now)
            except SlewResultError:
                return self._latch_fault(
                    FaultReason.SAFETY_INVARIANT,
                    event.ros_now,
                    event.monotonic_now,
                )
            self._command_pending = False
            self._command_published = True
            self._last_command_sent_stamp = event.ros_now
            self._command_pending = True
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

    def on_command_publish_failed(self, event: CommandPublishFailed) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._command_pending = False
            self._command_published = False
            self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

    def on_clear_fault_request(self, event: OperatorClearFaultRequest) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            if not self._fault_latched:
                if self._inconsistent():
                    return self._operation(
                        False,
                        ClearFaultCode.REJECTED_CONTROL_STATE,
                        "clear_fault rejected: control state is inconsistent",
                        event.ros_now,
                    )
                return self._operation(
                    True,
                    ClearFaultCode.ALREADY_CLEAR,
                    "fault already clear",
                    event.ros_now,
                )
            if self._inconsistent():
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_CONTROL_STATE,
                    "clear_fault rejected: control state is inconsistent",
                    event.ros_now,
                )
            if (
                self._last_heartbeat is None
                or event.monotonic_now - self._last_heartbeat
                > self._config.provider_heartbeat_timeout
            ):
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_COMMUNICATION_UNHEALTHY,
                    "clear_fault rejected: communication is unhealthy",
                    event.ros_now,
                )
            self._clear_fault_state = "awaiting_error"
            self._error_query_in_flight = True
            return [QueryErrorStatus()]

    def on_clear_fault_error_query(
        self,
        ok: bool,
        error_bits: tuple[int, ...] | None,
        monotonic_now: float,
        ros_now,
    ) -> list[Effect]:
        with self._lock:
            self._observe_clock(monotonic_now)
            if self._clear_fault_state != "awaiting_error":
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_CONTROL_STATE,
                    "clear_fault error query arrived outside protocol",
                    ros_now,
                )
            self._error_query_in_flight = False
            if not ok:
                self._clear_fault_state = "idle"
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_ERROR_QUERY_TIMEOUT,
                    "clear_fault rejected: error query timed out",
                    ros_now,
                )
            if error_bits is None or len(error_bits) != ACTIVE_JOINT_COUNT:
                self._clear_fault_state = "idle"
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_ERROR_STATUS_INVALID,
                    "clear_fault rejected: error status is invalid",
                    ros_now,
                )
            # commu_except (bit4) is a vendor-historical marker and is not a
            # fatal hardware error; it must not block clear_fault.
            if any(
                int(bit) & FATAL_ERROR_BIT_MASK != 0 for bit in error_bits
            ):
                self._hardware_error_bits = tuple(int(bit) for bit in error_bits)
                self._clear_fault_state = "idle"
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_HARDWARE_ERROR_PRESENT,
                    "clear_fault rejected: hardware error is present",
                    ros_now,
                )
            self._clear_fault_state = "awaiting_read"
            self._hardware_error_bits = (0,) * ACTIVE_JOINT_COUNT
            self._last_error = None
            return [RequestActiveJointsRead()]

    def on_clear_fault_read(
        self,
        ok: bool,
        feedback: JointFeedback | None,
        monotonic_now: float,
        ros_now,
    ) -> list[Effect]:
        with self._lock:
            self._observe_clock(monotonic_now)
            if self._clear_fault_state != "awaiting_read":
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_CONTROL_STATE,
                    "clear_fault read arrived outside protocol",
                    ros_now,
                )
            self._clear_fault_state = "idle"
            if not ok:
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_FEEDBACK_READ_TIMEOUT,
                    "clear_fault rejected: feedback read timed out",
                    ros_now,
                )
            if feedback is None:
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_FEEDBACK_INVALID,
                    "clear_fault rejected: feedback is invalid",
                    ros_now,
                )
            try:
                self._limiter.initialize(feedback.values, monotonic_now)
            except ValueError:
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_LIMITER_INIT_FAILED,
                    "clear_fault rejected: limiter initialization failed",
                    ros_now,
                )
            self._fault_latched = False
            self._fault_reasons.clear()
            self._feedback_ready = True
            self._error_monitor_ready = True
            self._last_heartbeat = monotonic_now
            self._last_feedback_received_stamp = ros_now
            self._phase = self._phase_for(ros_now)
            return self._operation(
                True, ClearFaultCode.SUCCESS, "fault cleared", ros_now
            )

    def check_timeouts(self, event: TimeoutCheck) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            if self._clear_fault_state != "idle":
                return []
            now = event.monotonic_now
            if self._command_pending and self._last_command_monotonic is not None:
                if now - self._last_command_monotonic > self._config.command_readback_timeout:
                    return self._latch_fault(
                        FaultReason.COMMAND_READBACK_TIMEOUT,
                        event.ros_now,
                        now,
                    )
            if self._feedback_ready and self._last_heartbeat is not None:
                if now - self._last_heartbeat > self._config.provider_heartbeat_timeout:
                    return self._latch_fault(
                        FaultReason.COMPONENT_RESTART_OR_DISCONNECT,
                        event.ros_now,
                        now,
                    )
            effects = self._maybe_query_error(now, event.ros_now)
            if (
                not self._feedback_ready
                and not self._read_in_flight
                and now - self._last_read_request >= self._config.init_read_retry_period
            ):
                self._read_in_flight = True
                self._last_read_request = now
                effects.append(RequestActiveJointsRead())
            fresh_now = self._fresh_at(event.ros_now)
            if fresh_now != self._last_published_target_fresh:
                effects.extend(
                    self._publish(
                        Trigger.TARGET_PROCESSED if fresh_now else Trigger.TARGET_TIMEOUT,
                        event.ros_now,
                    )
                )
            return effects

    def _on_target(self, event: TargetReceived) -> list[Effect]:
        target, reason, _ = validate_soft_target(event.value, self._config)
        if target is None:
            self._target_result = reason
            self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)
        self._target_ready = True
        self._last_target = target
        self._last_target_input_stamp = target.stamp
        self._last_target_received_stamp = event.received_at
        self._last_target_received_monotonic = event.monotonic_now
        if not self._fresh_at(event.ros_now):
            self._target_result = TargetResult.VALID_MOTION_DISABLED
            self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)
        if not self._motion_enabled(event.ros_now):
            self._target_result = TargetResult.VALID_MOTION_DISABLED
            self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)
        return self._emit_command(target, event.monotonic_now, event.ros_now)

    def _on_feedback(self, event: FeedbackReceived) -> list[Effect]:
        try:
            self._adopt_feedback(
                event.feedback, event.received_at, event.monotonic_now
            )
        except ValueError:
            return self._latch_fault(
                FaultReason.INVALID_FEEDBACK,
                event.received_at,
                event.monotonic_now,
            )
        self._command_pending = False
        return self._publish(Trigger.FEEDBACK_RECEIVED, event.received_at)

    def _maybe_query_error(self, now: float, ros_now) -> list[Effect]:
        if self._error_query_in_flight:
            if now <= self._error_query_deadline:
                return []
            self._error_query_in_flight = False
            if self._error_monitor_ready:
                return self._latch_fault(
                    FaultReason.ERROR_MONITOR_TIMEOUT, ros_now, now
                )
        period = (
            self._config.error_poll_period
            if self._error_monitor_ready
            else self._config.init_error_retry_period
        )
        if now - self._last_error_query >= period:
            self._error_query_in_flight = True
            self._error_query_deadline = now + self._config.error_query_timeout
            self._last_error_query = now
            return [QueryErrorStatus()]
        return []

    def _fresh_at(self, ros_now, monotonic_now: float | None = None) -> bool:
        if self._last_target_input_stamp is None or self._last_target_received_stamp is None:
            return False
        input_age = ros_now.seconds - self._last_target_input_stamp.seconds
        if monotonic_now is None:
            monotonic_now = self._last_monotonic_observed
        if self._last_target_received_monotonic is None:
            return False
        receive_age = monotonic_now - self._last_target_received_monotonic
        return (
            0.0 <= input_age <= self._config.target_input_stale_timeout
            and 0.0 <= receive_age <= self._config.target_receive_stale_timeout
        )

    def _motion_enabled(self, ros_now) -> bool:
        return (
            self._feedback_ready
            and self._error_monitor_ready
            and self._target_ready
            and self._fresh_at(ros_now)
            and not self._fault_latched
        )

    def _phase_for(self, ros_now) -> Phase:
        if self._fault_latched:
            return Phase.FAULT_LATCHED
        if not self._feedback_ready or not self._error_monitor_ready:
            return Phase.INITIALIZING
        if self._fresh_at(ros_now):
            return Phase.ACTIVE
        if self._target_ready:
            return Phase.PAUSED_TARGET_STALE
        return Phase.IDLE_READY

    def _emit_command(self, target: JointTarget, monotonic_now: float, ros_now) -> list[Effect]:
        try:
            values, flags = self._limiter.limit(
                target.values, monotonic_now, self._config.slew_compare_epsilon
            )
        except (SlewUnavailableError, SlewTimeError, SlewResultError):
            return self._latch_fault(FaultReason.SAFETY_INVARIANT, ros_now, monotonic_now)
        self._target_result = TargetResult.SENT
        self._slew_limited = tuple(bool(value) for value in flags)
        self._command_pending = True
        self._command_published = False
        self._last_command_monotonic = monotonic_now
        return [
            SendJointCommand(
                JointTarget(self._config.side, tuple(float(v) for v in values), target.stamp),
                monotonic_now,
            )
        ]

    def _adopt_feedback(
        self, feedback: JointFeedback, received_at, monotonic_now: float
    ) -> None:
        if not self._limiter.initialized:
            self._limiter.initialize(feedback.values, monotonic_now)
        self._feedback_ready = True
        self._last_feedback_received_stamp = received_at
        self._phase = self._phase_for(received_at)

    def _latch_fault(self, reason: FaultReason, ros_now, monotonic_now) -> list[Effect]:
        self._fault_reasons.add(reason)
        self._fault_latched = True
        self._command_pending = False
        self._command_published = False
        self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
        if self._limiter.initialized:
            self._limiter.clear_time_credit()
        self._phase = Phase.FAULT_LATCHED
        return self._publish(Trigger.FAULT_CHANGED, ros_now)

    def _inconsistent(self) -> bool:
        return self._fault_latched != (self._phase is Phase.FAULT_LATCHED) or (
            self._phase is Phase.FAULT_LATCHED and not self._fault_reasons
        )

    def _operation(self, success, code, message, ros_now) -> list[Effect]:
        self._command_published = False
        self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
        return [
            OperationResult(
                success=success,
                result_code=code,
                message=message,
                state=self._snapshot(Trigger.OPERATOR_REQUEST, ros_now),
            )
        ]

    def _publish(self, trigger: Trigger, ros_now) -> list[Effect]:
        state = self._snapshot(trigger, ros_now)
        self._last_published_target_fresh = state.target_fresh
        self._command_published = False
        self._slew_limited = (False,) * ACTIVE_JOINT_COUNT
        return [PublishControlState(state)]

    def _observe_clock(self, monotonic_now: float) -> None:
        self._last_monotonic_observed = monotonic_now

    def _snapshot(self, trigger: Trigger, ros_now) -> ControlStateSnapshot:
        phase = self._phase_for(ros_now)
        self._phase = phase
        return ControlStateSnapshot(
            side=self._config.side,
            trigger=trigger,
            phase=phase,
            feedback_ready=self._feedback_ready,
            error_monitor_ready=self._error_monitor_ready,
            target_ready=self._target_ready,
            target_fresh=self._fresh_at(ros_now),
            fault_latched=self._fault_latched,
            motion_enabled=self._motion_enabled(ros_now),
            target_result=self._target_result,
            command_published=self._command_published,
            slew_limited=(
                self._slew_limited
                if self._command_published
                else (False,) * ACTIVE_JOINT_COUNT
            ),
            fault_reasons=frozenset(self._fault_reasons),
            hardware_error_bits=self._hardware_error_bits,
            last_target_input_stamp=self._last_target_input_stamp,
            last_target_received_stamp=self._last_target_received_stamp,
            last_command_sent_stamp=self._last_command_sent_stamp,
            last_feedback_received_stamp=self._last_feedback_received_stamp,
            last_error_status_received_stamp=self._last_error_status_received_stamp,
        )
