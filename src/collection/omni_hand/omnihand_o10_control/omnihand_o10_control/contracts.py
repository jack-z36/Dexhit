"""Pure O10 control events, effects, semantic values and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeAlias

from omnihand_o10_contracts import (
    ACTIVE_JOINT_COUNT,
    JointError,
    JointFeedback,
    JointSampleTime,
    JointTarget,
    Side,
)

__all__ = [
    "Phase",
    "Trigger",
    "TargetResult",
    "TargetRejectReason",
    "FaultReason",
    "VENDOR_ERROR_BIT_COMMU_EXCEPT",
    "FATAL_ERROR_BIT_MASK",
    "ArmCode",
    "DisarmCode",
    "ClearFaultCode",
    "ControlConfig",
    "SoftTargetValue",
    "ControlStateSnapshot",
    "TargetReceived",
    "FeedbackReceived",
    "InvalidFeedbackReceived",
    "ErrorStatusReceived",
    "InvalidErrorStatusReceived",
    "ReadActiveJointsResult",
    "ReadActiveJointsTimeout",
    "CommandSent",
    "CommandPublishFailed",
    "OperatorArmRequest",
    "OperatorDisarmRequest",
    "OperatorClearFaultRequest",
    "TimeoutCheck",
    "Effect",
    "QueryErrorStatus",
    "SendJointCommand",
    "RequestActiveJointsRead",
    "PublishControlState",
    "OperationResult",
]


class Phase(Enum):
    """Semantic lifecycle phase; the ROS adapter owns its wire value."""

    INITIALIZING = auto()
    DISARMED_NOT_READY = auto()
    DISARMED_READY = auto()
    ACTIVE = auto()
    PAUSED_TARGET_STALE = auto()
    FAULT_LATCHED = auto()

    # Semantic compatibility aliases for callers that used the pre-wire
    # vocabulary; these are not wire values.
    UNINITIALIZED = INITIALIZING
    DISARMED = DISARMED_NOT_READY
    FAULT = FAULT_LATCHED


class Trigger(Enum):
    """Semantic event label; the ROS adapter owns its wire value."""

    STARTUP = auto()
    TARGET_PROCESSED = auto()
    TARGET_TIMEOUT = auto()
    FEEDBACK_RECEIVED = auto()
    ERROR_STATUS_RECEIVED = auto()
    OPERATOR_REQUEST = auto()
    FAULT_CHANGED = auto()
    COMPONENT_STATE_CHANGED = auto()

    FEEDBACK_UPDATE = FEEDBACK_RECEIVED
    OPERATOR_ARM = OPERATOR_REQUEST
    OPERATOR_DISARM = OPERATOR_REQUEST
    OPERATOR_CLEAR_FAULT = OPERATOR_REQUEST
    FAULT = FAULT_CHANGED
    PROVIDER_CHANGE = COMPONENT_STATE_CHANGED


class TargetResult(Enum):
    """Semantic result for the most recently evaluated target event."""

    NOT_EVALUATED = auto()
    SENT = auto()
    VALID_MOTION_DISABLED = auto()
    REJECTED_SCHEMA = auto()
    REJECTED_NAME_ORDER = auto()
    REJECTED_NONFINITE = auto()
    REJECTED_LIMIT = auto()
    REJECTED_AUX_FIELDS = auto()
    REJECTED_TIMESTAMP = auto()
    REJECTED_CONTROL_STATE = auto()

    # These names describe validation categories, not wire fields.
    OK = SENT
    REJECT_NAME = REJECTED_NAME_ORDER
    REJECT_POSITION = REJECTED_SCHEMA
    REJECT_HEADER = REJECTED_TIMESTAMP
    REJECT_STALE = REJECTED_TIMESTAMP
    REJECT_NONEMPTY_VELOCITY_EFFORT = REJECTED_AUX_FIELDS
    REJECT_NONFINITE = REJECTED_NONFINITE
    REJECT_SIDE_LIMIT = REJECTED_LIMIT


# Kept as a package-local semantic alias for existing pure validation imports.
TargetRejectReason = TargetResult


# Vendor O10 per-joint error-word bit layout (Agilink SDK / official ROS2
# contract, bit indices are 0-based):
#   bit0 = stalled, bit1 = overheat, bit2 = over_current,
#   bit3 = motor_except, bit4 = commu_except.
# The vendor treats bit4 (commu_except) as a HISTORICAL communication marker
# ("may indicate historical communication errors ... normal if the device had
# previous communication timeouts", official SDK test suite); it does not stop
# vendor-side control. Only bits 0-3 represent an actual current hardware fault.
VENDOR_ERROR_BIT_COMMU_EXCEPT: int = 1 << 4
#: Mask of error-word bits that latch a HARDWARE_ERROR control fault.
FATAL_ERROR_BIT_MASK: int = 0xFFFF & ~VENDOR_ERROR_BIT_COMMU_EXCEPT


class FaultReason(Enum):
    """Semantic fault reason; the ROS adapter owns its bit value."""

    HARDWARE_ERROR = auto()
    COMMAND_READBACK_TIMEOUT = auto()
    INVALID_FEEDBACK = auto()
    SAFETY_INVARIANT = auto()
    COMPONENT_RESTART_OR_DISCONNECT = auto()
    ERROR_MONITOR_TIMEOUT = auto()

    VENDOR_ERROR_BIT = HARDWARE_ERROR
    ILLEGAL_FEEDBACK = INVALID_FEEDBACK
    RESTART_DISCONNECT = COMPONENT_RESTART_OR_DISCONNECT


class ArmCode(Enum):
    """Semantic arm result; the ROS adapter owns its wire value."""

    SUCCESS = auto()
    ALREADY_ARMED = auto()
    REJECTED_FAULT_LATCHED = auto()
    REJECTED_FEEDBACK_NOT_READY = auto()
    REJECTED_ERROR_MONITOR_NOT_READY = auto()
    REJECTED_TARGET_NOT_READY = auto()
    REJECTED_TARGET_STALE = auto()
    REJECTED_CONTROL_STATE = auto()


class DisarmCode(Enum):
    """Semantic disarm result; the ROS adapter owns its wire value."""

    SUCCESS = auto()
    ALREADY_DISARMED = auto()
    REJECTED_CONTROL_STATE = auto()


class ClearFaultCode(Enum):
    """Semantic clear-fault result; the ROS adapter owns its wire value."""

    SUCCESS = auto()
    ALREADY_CLEAR = auto()
    REJECTED_CONTROL_STATE = auto()
    REJECTED_COMMUNICATION_UNHEALTHY = auto()
    REJECTED_ERROR_QUERY_TIMEOUT = auto()
    REJECTED_ERROR_STATUS_INVALID = auto()
    REJECTED_HARDWARE_ERROR_PRESENT = auto()
    REJECTED_FEEDBACK_READ_TIMEOUT = auto()
    REJECTED_FEEDBACK_INVALID = auto()
    REJECTED_LIMITER_INIT_FAILED = auto()


def _finite_positive(value: object, name: str) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


def _ten_finite(value: object, name: str) -> tuple[float, ...]:
    import math

    if not isinstance(value, (tuple, list)) or len(value) != ACTIVE_JOINT_COUNT:
        raise ValueError(f"{name} must contain {ACTIVE_JOINT_COUNT} values")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must contain only finite values")
    return result


@dataclass(frozen=True)
class ControlConfig:
    """Explicitly supplied safety, timing and limiter parameters."""

    side: Side
    max_joint_rates: tuple[float, ...]
    max_time_credit: float
    slew_compare_epsilon: tuple[float, ...]
    target_input_stale_timeout: float
    target_receive_stale_timeout: float
    control_check_period: float
    error_poll_period: float
    error_query_timeout: float
    command_readback_timeout: float
    provider_heartbeat_timeout: float
    init_read_retry_period: float
    init_error_retry_period: float
    read_service_timeout: float
    clear_fault_error_timeout: float
    clear_fault_read_timeout: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Side.from_value(self.side))
        object.__setattr__(
            self, "max_joint_rates", _ten_finite(self.max_joint_rates, "max_joint_rates")
        )
        object.__setattr__(
            self,
            "slew_compare_epsilon",
            _ten_finite(self.slew_compare_epsilon, "slew_compare_epsilon"),
        )
        for name in (
            "max_time_credit",
            "target_input_stale_timeout",
            "target_receive_stale_timeout",
            "control_check_period",
            "error_poll_period",
            "error_query_timeout",
            "command_readback_timeout",
            "provider_heartbeat_timeout",
            "init_read_retry_period",
            "init_error_retry_period",
            "read_service_timeout",
            "clear_fault_error_timeout",
            "clear_fault_read_timeout",
        ):
            object.__setattr__(self, name, _finite_positive(getattr(self, name), name))


@dataclass(frozen=True)
class SoftTargetValue:
    """Raw target fields entering the Application for validation."""

    side: Side
    name: tuple[str, ...]
    position: tuple[float, ...]
    velocity_empty: bool
    effort_empty: bool
    frame_id: str
    input_stamp: JointSampleTime | None
    received_at: JointSampleTime


@dataclass(frozen=True)
class ControlStateSnapshot:
    """Atomic pure snapshot matching the O10ControlState wire fields."""

    side: Side
    trigger: Trigger
    phase: Phase
    feedback_ready: bool
    error_monitor_ready: bool
    target_ready: bool
    target_fresh: bool
    armed: bool
    fault_latched: bool
    motion_enabled: bool
    target_result: TargetResult
    command_published: bool
    slew_limited: tuple[bool, ...]
    fault_reasons: frozenset[FaultReason]
    hardware_error_bits: tuple[int, ...]
    last_target_input_stamp: JointSampleTime | None
    last_target_received_stamp: JointSampleTime | None
    last_command_sent_stamp: JointSampleTime | None
    last_feedback_received_stamp: JointSampleTime | None
    last_error_status_received_stamp: JointSampleTime | None


@dataclass(frozen=True)
class TargetReceived:
    """A raw target and explicit local receive times entered the aggregate."""

    value: SoftTargetValue
    received_at: JointSampleTime
    monotonic_now: float
    ros_now: JointSampleTime


@dataclass(frozen=True)
class FeedbackReceived:
    """A validated real joint-position feedback frame arrived."""

    feedback: JointFeedback
    received_at: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class InvalidFeedbackReceived:
    """The Provider delivered an illegal feedback frame."""

    side: Side
    reason: str
    received_at: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class ErrorStatusReceived:
    """A validated Provider error status arrived."""

    error: JointError
    received_at: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class InvalidErrorStatusReceived:
    """The Provider delivered an illegal error status."""

    side: Side
    reason: str
    received_at: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class ReadActiveJointsResult:
    """Outcome of a fresh active-joint read effect."""

    success: bool
    feedback: JointFeedback | None
    received_at: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class ReadActiveJointsTimeout:
    """A fresh active-joint read effect exceeded its client timeout."""

    monotonic_now: float


@dataclass(frozen=True)
class CommandSent:
    """Confirmation that the runtime successfully published a command."""

    command: JointTarget
    ros_now: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class CommandPublishFailed:
    """The runtime failed to publish a command effect."""

    ros_now: JointSampleTime
    monotonic_now: float


@dataclass(frozen=True)
class OperatorArmRequest:
    monotonic_now: float
    ros_now: JointSampleTime


@dataclass(frozen=True)
class OperatorDisarmRequest:
    monotonic_now: float
    ros_now: JointSampleTime


@dataclass(frozen=True)
class OperatorClearFaultRequest:
    monotonic_now: float
    ros_now: JointSampleTime


@dataclass(frozen=True)
class TimeoutCheck:
    monotonic_now: float
    ros_now: JointSampleTime


@dataclass(frozen=True)
class QueryErrorStatus:
    """Effect: ask the Provider for a current error status."""


@dataclass(frozen=True)
class SendJointCommand:
    """Effect: publish one final hard-limited position command."""

    command: JointTarget
    monotonic_now: float


@dataclass(frozen=True)
class RequestActiveJointsRead:
    """Effect: request one fresh no-motion active-joint read."""


@dataclass(frozen=True)
class PublishControlState:
    """Effect: publish one event-driven pure state snapshot."""

    state: ControlStateSnapshot


@dataclass(frozen=True)
class OperationResult:
    """Effect: return one semantic operator-operation result."""

    success: bool
    result_code: Enum
    message: str
    state: ControlStateSnapshot


Effect: TypeAlias = (
    QueryErrorStatus
    | SendJointCommand
    | RequestActiveJointsRead
    | PublishControlState
    | OperationResult
)
