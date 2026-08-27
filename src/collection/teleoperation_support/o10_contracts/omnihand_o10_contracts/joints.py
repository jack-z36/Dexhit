"""The single O10 active-joint contract: names, indices and per-side limits.

This module is the ONLY code owner (ARCHITECTURE invariant A11) of:

* the fixed order and spelling of the 10 active joint names (Spec decision 24);
* their indices; and
* their per-side (left / right) position limits in radians.

Every other package that needs these facts MUST import them from here. The wire
schema (ROS ``.msg``/``.srv``) lives in ``rokoko_omnihand_msgs``; this package
owns only the pure runtime values.

The 10 active joints are fixed (Spec decision 2 / 24):

    thumb_roll, thumb_abad, thumb_mcp,
    index_abad, index_pip,
    middle_pip,
    ring_abad, ring_pip,
    pinky_abad, pinky_pip

Left and right use their own signs and limits (Spec decision 24).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .side import Side

__all__ = [
    "ACTIVE_JOINT_COUNT",
    "ACTIVE_JOINT_NAMES",
    "ACTIVE_JOINT_INDEX",
    "JointLimits",
    "JOINT_LIMITS",
]

#: Number of active O10 finger joints that the system commands (Spec decision 2).
ACTIVE_JOINT_COUNT: int = 10

#: Fixed active-joint order (Spec decision 24). Frozen; the single source of names.
ACTIVE_JOINT_NAMES: tuple[str, ...] = (
    "thumb_roll",
    "thumb_abad",
    "thumb_mcp",
    "index_abad",
    "index_pip",
    "middle_pip",
    "ring_abad",
    "ring_pip",
    "pinky_abad",
    "pinky_pip",
)

#: Name -> fixed index, derived once from :data:`ACTIVE_JOINT_NAMES`.
ACTIVE_JOINT_INDEX: dict[str, int] = {
    name: index for index, name in enumerate(ACTIVE_JOINT_NAMES)
}

# Per-side position limits in radians. Left and right differ in sign and range
# (Spec decision 24). These are the authoritative runtime values; the geometric
# model (URDF/MJCF) is the physical source, and this package is their single
# runtime code owner.
_RIGHT_LOWER = (
    -0.029670597283903602, -1.642354826126664, 0.0,
    -0.16406094968746698, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
)
_RIGHT_UPPER = (
    1.1213740444063567, 0.04537856055185257, 0.8415977653116657,
    0.0, 1.4835298641951802, 1.4835298641951802,
    0.16929693744344995, 1.4835298641951802,
    0.1850049007113989, 1.4835298641951802,
)
_LEFT_LOWER = (
    -1.1213740444063567, -0.04537856055185257, -0.8415977653116657,
    0.0, 0.0, 0.0, -0.16929693744344995, 0.0,
    -0.1850049007113989, 0.0,
)
_LEFT_UPPER = (
    0.029670597283903602, 1.642354826126664, 0.0,
    0.16406094968746698, 1.4835298641951802, 1.4835298641951802,
    0.0, 1.4835298641951802, 0.0, 1.4835298641951802,
)


def _frozen_vector(values: tuple[float, ...]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    arr.flags.writeable = False
    return arr


@dataclass(frozen=True)
class JointLimits:
    """Per-side inclusive radian limits for the 10 active joints.

    Both ``lower`` and ``upper`` are read-only float64 arrays of length
    :data:`ACTIVE_JOINT_COUNT`, aligned with :data:`ACTIVE_JOINT_NAMES`.
    """

    side: Side
    lower: np.ndarray
    upper: np.ndarray

    def __post_init__(self) -> None:
        if self.lower.shape != (ACTIVE_JOINT_COUNT,):
            raise ValueError(
                f"lower limits must be {ACTIVE_JOINT_COUNT}-dimensional, "
                f"got shape {self.lower.shape}"
            )
        if self.upper.shape != (ACTIVE_JOINT_COUNT,):
            raise ValueError(
                f"upper limits must be {ACTIVE_JOINT_COUNT}-dimensional, "
                f"got shape {self.upper.shape}"
            )
        if not np.all(self.lower <= self.upper):
            raise ValueError("lower limits must not exceed upper limits")

    def contains(self, values: np.ndarray) -> bool:
        """Return True iff every component is finite and within [lower, upper]."""
        arr = np.asarray(values, dtype=np.float64)
        return (
            arr.shape == (ACTIVE_JOINT_COUNT,)
            and np.all(np.isfinite(arr))
            and np.all(arr >= self.lower)
            and np.all(arr <= self.upper)
        )


JOINT_LIMITS: dict[Side, JointLimits] = {
    Side.RIGHT: JointLimits(
        side=Side.RIGHT,
        lower=_frozen_vector(_RIGHT_LOWER),
        upper=_frozen_vector(_RIGHT_UPPER),
    ),
    Side.LEFT: JointLimits(
        side=Side.LEFT,
        lower=_frozen_vector(_LEFT_LOWER),
        upper=_frozen_vector(_LEFT_UPPER),
    ),
}
