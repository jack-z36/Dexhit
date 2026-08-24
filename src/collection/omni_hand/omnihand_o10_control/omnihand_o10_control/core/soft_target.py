"""Pure soft-target validation for one side (control entrance, doc 02).

The control session owns the target validation rules and reject reasons; this
module implements them against the pure contracts value objects.  A rejected
target never reaches the limiter and never produces a command effect.
"""

from __future__ import annotations

from omnihand_o10_contracts import (
    ACTIVE_JOINT_COUNT,
    ACTIVE_JOINT_NAMES,
    InvalidJointVectorError,
    JointTarget,
)

from ..contracts import ControlConfig, SoftTargetValue, TargetResult

__all__ = ["validate_soft_target"]


def validate_soft_target(
    value: SoftTargetValue,
    config: ControlConfig,
) -> tuple[JointTarget | None, TargetResult, str]:
    """Validate one soft target, in the documented precedence order.

    Returns ``(JointTarget | None, reason, message)``.  A rejection reason is
    the FIRST failed check; a success returns a valid, in-limit target carrying
    the upstream ``header.stamp``.
    """
    side = value.side
    if not config.side == side:
        return (
            None,
            TargetResult.REJECTED_NAME_ORDER,
            f"soft target side {side.value!r} does not match control side "
            f"{config.side.value!r}",
        )

    if len(value.position) != ACTIVE_JOINT_COUNT:
        return (
            None,
            TargetResult.REJECTED_SCHEMA,
            f"soft target position must be {ACTIVE_JOINT_COUNT}-dimensional, "
            f"got {len(value.position)}",
        )

    if (
        len(value.name) != ACTIVE_JOINT_COUNT
        or len(set(value.name)) != ACTIVE_JOINT_COUNT
        or set(value.name) != set(ACTIVE_JOINT_NAMES)
    ):
        return (
            None,
            TargetResult.REJECTED_NAME_ORDER,
            "soft target must contain each active-joint name exactly once",
        )

    position_by_name = dict(zip(value.name, value.position))
    canonical_position = tuple(position_by_name[name] for name in ACTIVE_JOINT_NAMES)

    try:
        target = JointTarget(
            side=side,
            values=canonical_position,
            stamp=value.input_stamp if value.input_stamp is not None else value.received_at,
        )
    except InvalidJointVectorError as error:
        if error.reason in ("non_numeric", "non_finite"):
            return (
                None,
                TargetResult.REJECTED_NONFINITE,
                f"{side.value} soft target position is not finite: {error}",
            )
        if error.reason in ("below_limit", "above_limit"):
            return (
                None,
                TargetResult.REJECTED_LIMIT,
                f"{side.value} soft target position leaves the joint limits: {error}",
            )
        return (
            None,
            TargetResult.REJECTED_SCHEMA,
            f"{side.value} soft target position is invalid: {error}",
        )

    return target, TargetResult.SENT, "accepted"
