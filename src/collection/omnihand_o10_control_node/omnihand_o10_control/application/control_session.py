"""Minimal per-side O10 safety classifier and projector.

The only mutable business state is ``_state``: syncing, running from an
explicit command base, or faulted by a known fatal condition.  ROS-facing
diagnostics and slow-path polling bookkeeping are compatibility projections;
they never participate in the target fast-path decision.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    TargetResult,
    TimeoutCheck,
    Trigger,
)
from ..core.slew_limiter import project_slew
from ..core.soft_target import validate_soft_target

__all__ = ["ControlSession"]

_EXPLICIT_FATAL_HARDWARE_BITS = FATAL_ERROR_BIT_MASK & 0x0F


@dataclass(frozen=True)
class _Syncing:
    """No trusted command base exists yet."""


@dataclass(frozen=True)
class _Running:
    """A trusted last-sent position and monotonic origin exist."""

    base_position: tuple[float, ...]
    base_monotonic: float


@dataclass(frozen=True)
class _Faulted:
    """A known fatal hardware or internal safety condition is latched."""

    reason: FaultReason


_ControlState = _Syncing | _Running | _Faulted


@dataclass
class _Diagnostics:
    """Compatibility data for O10ControlState; never gates target handling."""

    error_monitor_seen: bool = False
    hardware_error_bits: tuple[int, ...] = (0,) * ACTIVE_JOINT_COUNT
    target_result: TargetResult = TargetResult.NOT_EVALUATED
    last_target_input_stamp: object | None = None
    last_target_received_stamp: object | None = None
    last_target_received_monotonic: float | None = None
    last_feedback_received_stamp: object | None = None
    last_error_status_received_stamp: object | None = None
    last_command_sent_stamp: object | None = None
    last_monotonic_observed: float = 0.0
    command_published: bool = False
    slew_limited: tuple[bool, ...] = (False,) * ACTIVE_JOINT_COUNT


@dataclass
class _Monitor:
    """Slow-path protocol bookkeeping isolated from the business state."""

    last_read_request: float = 0.0
    read_in_flight: bool = False
    last_error_query: float = 0.0
    error_query_in_flight: bool = False
    error_query_deadline: float = 0.0
    clear_fault_stage: str = "idle"


class ControlSession:
    """Classify and safely project commands for one logical hand side."""

    def __init__(self, config: ControlConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._state: _ControlState = _Syncing()
        self._diagnostics = _Diagnostics()
        self._monitor = _Monitor()

    def initial_snapshot(self, ros_now) -> ControlStateSnapshot:
        with self._lock:
            return self._snapshot(Trigger.STARTUP, ros_now)

    @property
    def clear_fault_in_progress(self) -> bool:
        with self._lock:
            return self._monitor.clear_fault_stage != "idle"

    def on_target(self, event: TargetReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            return self._on_target(event)

    def on_feedback(self, event: FeedbackReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._record_feedback(event.feedback, event.received_at)
            if isinstance(self._state, _Syncing):
                self._state = self._running_from_feedback(
                    event.feedback, event.monotonic_now
                )
            return self._publish(Trigger.FEEDBACK_RECEIVED, event.received_at)

    def on_invalid_feedback(self, event: InvalidFeedbackReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            return self._publish(Trigger.FEEDBACK_RECEIVED, event.received_at)

    def on_error_status(self, event: ErrorStatusReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            bits = tuple(int(value) for value in event.error.values)
            self._diagnostics.error_monitor_seen = True
            self._diagnostics.hardware_error_bits = bits
            self._diagnostics.last_error_status_received_stamp = event.received_at
            self._monitor.error_query_in_flight = False
            if any(value & _EXPLICIT_FATAL_HARDWARE_BITS != 0 for value in bits):
                return self._latch_fault(
                    FaultReason.HARDWARE_ERROR,
                    event.received_at,
                )
            return self._publish(Trigger.ERROR_STATUS_RECEIVED, event.received_at)

    def on_invalid_error_status(self, event: InvalidErrorStatusReceived) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._monitor.error_query_in_flight = False
            return []

    def on_read_result(self, event: ReadActiveJointsResult) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._monitor.read_in_flight = False
            if not event.success or event.feedback is None:
                return []
            self._record_feedback(event.feedback, event.received_at)
            if not isinstance(self._state, _Faulted):
                self._state = self._running_from_feedback(
                    event.feedback, event.monotonic_now
                )
            return self._publish(Trigger.FEEDBACK_RECEIVED, event.received_at)

    def on_read_timeout(self, event: ReadActiveJointsTimeout) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._monitor.read_in_flight = False
            return []

    def on_command_sent(self, event: CommandSent) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            if not isinstance(self._state, _Running):
                self._diagnostics.target_result = TargetResult.REJECTED_CONTROL_STATE
                return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)
            self._state = _Running(
                tuple(float(value) for value in event.command.values),
                event.monotonic_now,
            )
            self._diagnostics.command_published = True
            self._diagnostics.last_command_sent_stamp = event.ros_now
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

    def on_command_publish_failed(self, event: CommandPublishFailed) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            self._state = _Syncing()
            self._diagnostics.command_published = False
            self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

    def on_clear_fault_request(self, event: OperatorClearFaultRequest) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            if not isinstance(self._state, _Faulted):
                return self._operation(
                    True,
                    ClearFaultCode.ALREADY_CLEAR,
                    "fault already clear",
                    event.ros_now,
                )
            self._monitor.clear_fault_stage = "awaiting_error"
            self._monitor.error_query_in_flight = True
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
            if self._monitor.clear_fault_stage != "awaiting_error":
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_CONTROL_STATE,
                    "clear_fault error query arrived outside protocol",
                    ros_now,
                )
            self._monitor.error_query_in_flight = False
            if not ok:
                self._monitor.clear_fault_stage = "idle"
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_ERROR_QUERY_TIMEOUT,
                    "clear_fault rejected: error query timed out",
                    ros_now,
                )
            if error_bits is None or len(error_bits) != ACTIVE_JOINT_COUNT:
                self._monitor.clear_fault_stage = "idle"
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_ERROR_STATUS_INVALID,
                    "clear_fault rejected: error status is invalid",
                    ros_now,
                )
            bits = tuple(int(bit) for bit in error_bits)
            self._diagnostics.hardware_error_bits = bits
            if any(bit & _EXPLICIT_FATAL_HARDWARE_BITS != 0 for bit in bits):
                self._monitor.clear_fault_stage = "idle"
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_HARDWARE_ERROR_PRESENT,
                    "clear_fault rejected: hardware error is present",
                    ros_now,
                )
            self._monitor.clear_fault_stage = "awaiting_read"
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
            if self._monitor.clear_fault_stage != "awaiting_read":
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_CONTROL_STATE,
                    "clear_fault read arrived outside protocol",
                    ros_now,
                )
            self._monitor.clear_fault_stage = "idle"
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
                running = self._running_from_feedback(feedback, monotonic_now)
            except (TypeError, ValueError):
                return self._operation(
                    False,
                    ClearFaultCode.REJECTED_LIMITER_INIT_FAILED,
                    "clear_fault rejected: limiter initialization failed",
                    ros_now,
                )
            self._state = running
            self._diagnostics.hardware_error_bits = (0,) * ACTIVE_JOINT_COUNT
            self._diagnostics.error_monitor_seen = True
            self._record_feedback(feedback, ros_now)
            return self._operation(
                True,
                ClearFaultCode.SUCCESS,
                "fault cleared",
                ros_now,
            )

    def check_timeouts(self, event: TimeoutCheck) -> list[Effect]:
        with self._lock:
            self._observe_clock(event.monotonic_now)
            if self._monitor.clear_fault_stage != "idle":
                return []
            effects = self._maybe_query_error(event.monotonic_now)
            if (
                isinstance(self._state, _Syncing)
                and not self._monitor.read_in_flight
                and event.monotonic_now - self._monitor.last_read_request
                >= self._config.init_read_retry_period
            ):
                self._monitor.read_in_flight = True
                self._monitor.last_read_request = event.monotonic_now
                effects.append(RequestActiveJointsRead())
            return effects

    def _on_target(self, event: TargetReceived) -> list[Effect]:
        target, reason, _ = validate_soft_target(event.value, self._config)
        if target is None:
            self._diagnostics.target_result = reason
            self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

        self._diagnostics.last_target_input_stamp = target.stamp
        self._diagnostics.last_target_received_stamp = event.received_at
        self._diagnostics.last_target_received_monotonic = event.monotonic_now
        if not isinstance(self._state, _Running):
            self._diagnostics.target_result = TargetResult.VALID_MOTION_DISABLED
            self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

        try:
            values, flags = project_slew(
                side=self._config.side,
                base_position=self._state.base_position,
                base_monotonic=self._state.base_monotonic,
                soft_position=target.values,
                monotonic_now=event.monotonic_now,
                max_rates=self._config.max_joint_rates,
                max_time_credit=self._config.max_time_credit,
                compare_epsilon=self._config.slew_compare_epsilon,
            )
        except ValueError:
            self._diagnostics.target_result = TargetResult.REJECTED_CONTROL_STATE
            self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
            return self._publish(Trigger.TARGET_PROCESSED, event.ros_now)

        self._diagnostics.target_result = TargetResult.SENT
        self._diagnostics.slew_limited = tuple(bool(value) for value in flags)
        self._diagnostics.command_published = False
        return [
            SendJointCommand(
                JointTarget(
                    self._config.side,
                    tuple(float(value) for value in values),
                    target.stamp,
                ),
                event.monotonic_now,
            )
        ]

    def _maybe_query_error(self, now: float) -> list[Effect]:
        if self._monitor.error_query_in_flight:
            if now <= self._monitor.error_query_deadline:
                return []
            self._monitor.error_query_in_flight = False
        period = (
            self._config.error_poll_period
            if self._diagnostics.error_monitor_seen
            else self._config.init_error_retry_period
        )
        if now - self._monitor.last_error_query >= period:
            self._monitor.error_query_in_flight = True
            self._monitor.error_query_deadline = now + self._config.error_query_timeout
            self._monitor.last_error_query = now
            return [QueryErrorStatus()]
        return []

    def _target_fresh_for_diagnostics(self, ros_now) -> bool:
        input_stamp = self._diagnostics.last_target_input_stamp
        receive_stamp = self._diagnostics.last_target_received_stamp
        receive_monotonic = self._diagnostics.last_target_received_monotonic
        if input_stamp is None or receive_stamp is None or receive_monotonic is None:
            return False
        input_age = ros_now.seconds - input_stamp.seconds
        receive_age = (
            self._diagnostics.last_monotonic_observed - receive_monotonic
        )
        return (
            0.0 <= input_age <= self._config.target_input_stale_timeout
            and 0.0 <= receive_age <= self._config.target_receive_stale_timeout
        )

    def _phase(self) -> Phase:
        if isinstance(self._state, _Syncing):
            return Phase.INITIALIZING
        if isinstance(self._state, _Faulted):
            return Phase.FAULT_LATCHED
        if self._diagnostics.last_target_input_stamp is None:
            return Phase.IDLE_READY
        return Phase.ACTIVE

    def _latch_fault(self, reason: FaultReason, ros_now) -> list[Effect]:
        self._state = _Faulted(reason)
        self._diagnostics.command_published = False
        self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
        return self._publish(Trigger.FAULT_CHANGED, ros_now)

    def _operation(self, success, code, message, ros_now) -> list[Effect]:
        self._diagnostics.command_published = False
        self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
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
        self._diagnostics.command_published = False
        self._diagnostics.slew_limited = (False,) * ACTIVE_JOINT_COUNT
        return [PublishControlState(state)]

    def _snapshot(self, trigger: Trigger, ros_now) -> ControlStateSnapshot:
        faulted = isinstance(self._state, _Faulted)
        running = isinstance(self._state, _Running)
        fault_reasons = (
            frozenset((self._state.reason,)) if faulted else frozenset()
        )
        target_ready = self._diagnostics.last_target_input_stamp is not None
        return ControlStateSnapshot(
            side=self._config.side,
            trigger=trigger,
            phase=self._phase(),
            feedback_ready=running,
            error_monitor_ready=self._diagnostics.error_monitor_seen,
            target_ready=target_ready,
            target_fresh=self._target_fresh_for_diagnostics(ros_now),
            fault_latched=faulted,
            motion_enabled=running,
            target_result=self._diagnostics.target_result,
            command_published=self._diagnostics.command_published,
            slew_limited=(
                self._diagnostics.slew_limited
                if self._diagnostics.command_published
                else (False,) * ACTIVE_JOINT_COUNT
            ),
            fault_reasons=fault_reasons,
            hardware_error_bits=self._diagnostics.hardware_error_bits,
            last_target_input_stamp=self._diagnostics.last_target_input_stamp,
            last_target_received_stamp=self._diagnostics.last_target_received_stamp,
            last_command_sent_stamp=self._diagnostics.last_command_sent_stamp,
            last_feedback_received_stamp=self._diagnostics.last_feedback_received_stamp,
            last_error_status_received_stamp=(
                self._diagnostics.last_error_status_received_stamp
            ),
        )

    def _observe_clock(self, monotonic_now: float) -> None:
        self._diagnostics.last_monotonic_observed = monotonic_now

    def _record_feedback(self, feedback: JointFeedback, received_at) -> None:
        if feedback.side is not self._config.side:
            raise ValueError("feedback side does not match control side")
        self._diagnostics.last_feedback_received_stamp = received_at

    def _running_from_feedback(
        self, feedback: JointFeedback, monotonic_now: float
    ) -> _Running:
        if feedback.side is not self._config.side:
            raise ValueError("feedback side does not match control side")
        values = tuple(float(value) for value in feedback.values)
        if len(values) != ACTIVE_JOINT_COUNT:
            raise ValueError("feedback must contain 10 active joints")
        return _Running(values, float(monotonic_now))
