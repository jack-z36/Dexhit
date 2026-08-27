"""omnihand_o10_contracts -- the pure O10 shared type layer.

This package is the single code owner (ARCHITECTURE invariant A11) of:

* the logical hand :class:`Side`;
* the 10 active-joint names, indices and per-side limits; and
* the pure, validated joint target / feedback / error / time value objects
  shared by retargeting, control and providers.

It depends only on the Python standard library and numpy. It MUST NOT import
rclpy, ROS messages, Pinocchio, NLopt, vendor code or test code. See the
``test_import_guard`` module for the enforced purity contract.

Public surface
--------------

* :class:`Side` -- logical ``left`` / ``right`` hand side.
* :data:`ACTIVE_JOINT_COUNT`, :data:`ACTIVE_JOINT_NAMES`, :data:`ACTIVE_JOINT_INDEX`
  -- the fixed 10 active-joint contract (Spec decision 24).
* :data:`JOINT_LIMITS`, :class:`JointLimits` -- per-side rad limits.
* :class:`JointTarget`, :class:`JointFeedback` -- validated 10-dim rad
  position-domain value objects (finite, within per-side limits).
* :class:`JointError` -- validated 10-joint vendor error state.
* :class:`JointSampleTime` -- validated non-negative sample time.
"""

from __future__ import annotations

from .errors import (
    InvalidJointVectorError,
    InvalidSampleTimeError,
    InvalidSideError,
    O10ContractError,
)
from .joints import (
    ACTIVE_JOINT_COUNT,
    ACTIVE_JOINT_INDEX,
    ACTIVE_JOINT_NAMES,
    JOINT_LIMITS,
    JointLimits,
)
from .side import Side
from .values import JointError, JointFeedback, JointSampleTime, JointTarget

__all__ = [
    # Side
    "Side",
    # Active-joint contract
    "ACTIVE_JOINT_COUNT",
    "ACTIVE_JOINT_NAMES",
    "ACTIVE_JOINT_INDEX",
    "JointLimits",
    "JOINT_LIMITS",
    # Value objects
    "JointTarget",
    "JointFeedback",
    "JointError",
    "JointSampleTime",
    # Errors
    "O10ContractError",
    "InvalidSideError",
    "InvalidJointVectorError",
    "InvalidSampleTimeError",
]

__version__ = "0.1.0"
