"""Pure, validated O10 joint value objects.

These are the common type layer for retargeting, control and providers. Every
value object is immutable: construction either succeeds with a fully validated
object or raises a typed :class:`~omnihand_o10_contracts.errors.O10ContractError`.
Invalid input is never silently coerced, clamped or dropped.

Position-domain objects (:class:`JointTarget`, :class:`JointFeedback`) carry a
10-dimensional radian vector that must be finite and within the per-side limits.
:class:`JointError` carries the 10-joint vendor error state, which is validated
for dimension and finiteness only -- error bits are not position-domain radians,
so rad joint limits do not apply to them.

Each value object is tagged with the logical :class:`Side` it belongs to and a
sample time, so the two sides never share mutable state and downstream code can
reason about data age without a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

import numpy as np

from .errors import InvalidJointVectorError, InvalidSampleTimeError
from .joints import ACTIVE_JOINT_COUNT, JOINT_LIMITS
from .side import Side

__all__ = [
    "JointSampleTime",
    "JointTarget",
    "JointFeedback",
    "JointError",
]

#: A stamp may be supplied as an already-validated :class:`JointSampleTime` or as
#: raw non-negative seconds.
StampLike = Union["JointSampleTime", float, int]


@dataclass(frozen=True)
class JointSampleTime:
    """A validated, non-negative sample time in seconds.

    Used for soft-target timestamps (inheriting the triggering Raw receive time,
    Spec decision 32), feedback sample stamps and monotonic slew-limit instants.
    """

    seconds: float

    def __post_init__(self) -> None:
        value = float(self.seconds)
        if not np.isfinite(value):
            raise InvalidSampleTimeError(
                f"sample time must be finite, got {self.seconds!r}"
            )
        if value < 0.0:
            raise InvalidSampleTimeError(
                f"sample time must be non-negative, got {value}"
            )
        object.__setattr__(self, "seconds", value)


def _normalise_stamp(stamp: StampLike) -> JointSampleTime:
    if isinstance(stamp, JointSampleTime):
        return stamp
    return JointSampleTime(stamp)


def _frozen_vector(values) -> np.ndarray:
    """Return a defensive, read-only float64 copy of ``values``."""
    arr = np.array(values, dtype=np.float64, copy=True)
    arr.flags.writeable = False
    return arr


def _validate_position_vector(side: Side, values) -> np.ndarray:
    """Validate a 10-dim finite rad vector within ``side``'s per-side limits."""
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise InvalidJointVectorError(
            f"{side.value} joint vector is not numeric: {error}",
            side=side,
            reason="non_numeric",
        ) from error

    if arr.shape != (ACTIVE_JOINT_COUNT,):
        raise InvalidJointVectorError(
            f"{side.value} joint vector must be {ACTIVE_JOINT_COUNT}-dimensional, "
            f"got shape {tuple(arr.shape)}",
            side=side,
            reason="dimension",
        )

    finite = np.isfinite(arr)
    if not finite.all():
        index = int(np.argmax(~finite))
        raise InvalidJointVectorError(
            f"{side.value} joint {index} ({_joint_name(index)}) is not finite: "
            f"{arr[index]!r}",
            side=side,
            reason="non_finite",
            index=index,
            value=float(arr[index]),
        )

    limits = JOINT_LIMITS[side]
    below = arr < limits.lower
    above = arr > limits.upper
    if below.any():
        index = int(np.argmax(below))
        raise InvalidJointVectorError(
            f"{side.value} joint {index} ({_joint_name(index)}) value {arr[index]!r} "
            f"is below limit {limits.lower[index]!r}",
            side=side,
            reason="below_limit",
            index=index,
            value=float(arr[index]),
        )
    if above.any():
        index = int(np.argmax(above))
        raise InvalidJointVectorError(
            f"{side.value} joint {index} ({_joint_name(index)}) value {arr[index]!r} "
            f"is above limit {limits.upper[index]!r}",
            side=side,
            reason="above_limit",
            index=index,
            value=float(arr[index]),
        )

    return _frozen_vector(arr)


def _validate_error_vector(side: Side, values) -> np.ndarray:
    """Validate a 10-dim finite error-state vector (not checked against rad limits)."""
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise InvalidJointVectorError(
            f"{side.value} error vector is not numeric: {error}",
            side=side,
            reason="non_numeric",
        ) from error

    if arr.shape != (ACTIVE_JOINT_COUNT,):
        raise InvalidJointVectorError(
            f"{side.value} error vector must be {ACTIVE_JOINT_COUNT}-dimensional, "
            f"got shape {tuple(arr.shape)}",
            side=side,
            reason="dimension",
        )

    finite = np.isfinite(arr)
    if not finite.all():
        index = int(np.argmax(~finite))
        raise InvalidJointVectorError(
            f"{side.value} error component {index} is not finite: {arr[index]!r}",
            side=side,
            reason="non_finite",
            index=index,
            value=float(arr[index]),
        )

    return _frozen_vector(arr)


def _joint_name(index: int) -> str:
    from .joints import ACTIVE_JOINT_NAMES

    return ACTIVE_JOINT_NAMES[index]


@dataclass(frozen=True, eq=False)
class _JointVectorValue:
    """Common fields for the validated joint value objects.

    Equality and hashing are value-based (side, vector contents, stamp); the
    numpy array is compared with :func:`numpy.array_equal` and hashed from its
    bytes so immutable copies compare and hash consistently.
    """

    side: Side
    values: np.ndarray
    stamp: JointSampleTime = field(default_factory=lambda: JointSampleTime(0.0))

    @property
    def stamp_seconds(self) -> float:
        return self.stamp.seconds

    def as_tuple(self) -> tuple[float, ...]:
        return tuple(float(v) for v in self.values)

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return (
            self.side is other.side
            and self.stamp == other.stamp
            and np.array_equal(self.values, other.values)
        )

    def __ne__(self, other: object) -> bool:  # noqa: D401 - mirrors __eq__
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self) -> int:
        return hash((type(self), self.side, self.values.tobytes(), self.stamp))


@dataclass(frozen=True, eq=False)
class JointTarget(_JointVectorValue):
    """A validated 10-dim radian soft target / command for one logical side.

    Construction enforces: exactly 10 finite components, each within the side's
    per-side limits. The triggering timestamp (Spec decision 32) is carried by
    ``stamp``.
    """

    def __post_init__(self) -> None:
        vector = _validate_position_vector(self.side, self.values)
        stamp = _normalise_stamp(self.stamp)
        object.__setattr__(self, "side", Side.from_value(self.side))
        object.__setattr__(self, "values", vector)
        object.__setattr__(self, "stamp", stamp)


@dataclass(frozen=True, eq=False)
class JointFeedback(_JointVectorValue):
    """A validated 10-dim radian real joint-position feedback for one side.

    Used for the fresh, independent read that initialises the per-side hard slew
    limiter (CONTEXT.md: 硬限制器初始化反馈) and for ongoing feedback. The same
    position-domain validation as :class:`JointTarget` applies.
    """

    def __post_init__(self) -> None:
        vector = _validate_position_vector(self.side, self.values)
        stamp = _normalise_stamp(self.stamp)
        object.__setattr__(self, "side", Side.from_value(self.side))
        object.__setattr__(self, "values", vector)
        object.__setattr__(self, "stamp", stamp)


@dataclass(frozen=True, eq=False)
class JointError(_JointVectorValue):
    """The 10-joint vendor error state for one logical side.

    Each component represents a per-joint error indicator reported by the
    hardware adapter (Spec: 厂商错误位). Components must be finite; they are not
    radian positions and are therefore not checked against the joint limits.
    """

    def __post_init__(self) -> None:
        vector = _validate_error_vector(self.side, self.values)
        stamp = _normalise_stamp(self.stamp)
        object.__setattr__(self, "side", Side.from_value(self.side))
        object.__setattr__(self, "values", vector)
        object.__setattr__(self, "stamp", stamp)
