"""Pure values crossing the retargeting Core/Application boundary."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TypeAlias

Vector3: TypeAlias = tuple[float, float, float]
Matrix3: TypeAlias = tuple[Vector3, Vector3, Vector3]

NODE_SUFFIXES = (
    "Hand",
    "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
    "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
    "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
    "RingProximal", "RingMedial", "RingDistal", "RingTip",
    "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
)


@dataclass(frozen=True)
class RawHandFrameValue:
    """The position subset consumed from the validated RawHandFrame wire value."""

    node_names: tuple[str, ...]
    positions: tuple[Vector3, ...]
    received_at_ns: int


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _five_positive(values: object, name: str) -> tuple[float, ...]:
    if not isinstance(values, (tuple, list)) or len(values) != 5:
        raise ValueError(f"{name} must contain five values")
    return tuple(_positive_number(value, name) for value in values)


@dataclass(frozen=True)
class RetargetingConfig:
    """Uncalibrated T05 parameters; every value must be supplied explicitly."""

    palm_y_epsilon: float
    palm_x_epsilon: float
    finger_length_epsilon: float
    length_window_size: int
    stable_window_count: int
    length_nmad_thresholds: tuple[float, ...]
    frozen_length_relative_thresholds: tuple[float, ...]
    ik_residual_thresholds: tuple[float, ...]
    ik_max_evaluations: int
    ik_max_time_sec: float
    smooth_time_constants: tuple[float, ...]
    stale_timeout_sec: float
    recovery_min_valid_frames: int
    recovery_min_duration_sec: float
    recovery_confirmation_timeout_sec: float

    def __post_init__(self) -> None:
        for name in ("palm_y_epsilon", "palm_x_epsilon", "finger_length_epsilon"):
            object.__setattr__(self, name, _positive_number(getattr(self, name), name))
        for name in ("length_window_size", "stable_window_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("length_nmad_thresholds", "frozen_length_relative_thresholds"):
            object.__setattr__(self, name, _five_positive(getattr(self, name), name))
        object.__setattr__(
            self, "ik_residual_thresholds",
            _five_positive(self.ik_residual_thresholds, "ik_residual_thresholds"),
        )
        object.__setattr__(
            self, "smooth_time_constants",
            _positive_vector(self.smooth_time_constants, 10, "smooth_time_constants"),
        )
        for name in ("ik_max_evaluations", "recovery_min_valid_frames"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "ik_max_time_sec", "stale_timeout_sec", "recovery_min_duration_sec",
            "recovery_confirmation_timeout_sec",
        ):
            object.__setattr__(self, name, _positive_number(getattr(self, name), name))


@dataclass(frozen=True)
class RetargetingDecision:
    """
    Pure per-event snapshot returned by one side's session.

    The five-element fields use the wire contract order ``T, I, M, R, L``.
    They deliberately contain no ROS enum numbers; the runtime adapter is the
    sole place that translates these semantic values to ``RetargetingState``.
    """

    phase: str
    side_valid: bool
    all_lengths_frozen: bool
    command_published: bool
    length_frozen: tuple[bool, ...]
    length_current_valid: tuple[bool, ...]
    targets: tuple[Vector3 | None, ...] | None
    input_stamp_ns: int
    ik_state: tuple[str, ...]
    has_valid_ik: tuple[bool, ...]
    used_previous_valid_target: tuple[bool, ...]
    residual_available: tuple[bool, ...]
    normalized_residual: tuple[float, ...]
    # ``None`` is the pure-layer representation of the wire contract's
    # SOLVER_NOT_RUN value.  The ROS adapter resolves it from the generated
    # message definition, including when that definition has not yet exposed
    # the name as a Python constant.
    solver_result_code: tuple[int | None, ...]
    solver_evaluations: tuple[int, ...]
    solve_executed: bool = False
    command_stamp_ns: int | None = None
    command_positions: tuple[float, ...] | None = None
    stale: bool = False
    recovery_valid_count: int = 0
    recovery_valid_duration_sec: float = 0.0
    solve_duration_sec: float = math.nan
    solve_finished_at_ns: int | None = None
    # Projection diagnostics are independent of IK residual diagnostics.  An
    # identity target is available with distance zero; all other unavailable
    # cases stay unavailable with NaN rather than using a sentinel distance.
    target_projection_applied: tuple[bool, ...] = (False,) * 5
    target_projection_distance_available: tuple[bool, ...] = (False,) * 5
    normalized_target_projection_distance: tuple[float, ...] = (math.nan,) * 5


def _positive_vector(value: object, size: int, name: str) -> tuple[float, ...]:
    if not isinstance(value, (tuple, list)) or len(value) != size:
        raise ValueError(f"{name} must contain {size} values")
    return tuple(_positive_number(item, name) for item in value)
