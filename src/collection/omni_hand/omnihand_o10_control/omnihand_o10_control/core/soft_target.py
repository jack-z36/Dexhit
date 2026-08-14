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
    Side,
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

    if value.name != ACTIVE_JOINT_NAMES:
        return (
            None,
            TargetResult.REJECTED_NAME_ORDER,
            f"soft target name must be the fixed {len(ACTIVE_JOINT_NAMES)} "
            "active-joint names in contract order",
        )

    if len(value.position) != ACTIVE_JOINT_COUNT:
        return (
            None,
            TargetResult.REJECTED_SCHEMA,
            f"soft target position must be {ACTIVE_JOINT_COUNT}-dimensional, "
            f"got {len(value.position)}",
        )

    try:
        target = JointTarget(
            side=side,
            values=value.position,
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

    if not value.velocity_empty or not value.effort_empty:
        return (
            None,
            TargetResult.REJECTED_AUX_FIELDS,
            f"{side.value} soft target must leave velocity and effort empty",
        )

    if value.frame_id != "":
        return (
            None,
            TargetResult.REJECTED_TIMESTAMP,
            f"{side.value} soft target frame_id must be empty, got "
            f"{value.frame_id!r}",
        )

    if value.input_stamp is None:
        return (
            None,
            TargetResult.REJECTED_TIMESTAMP,
            f"{side.value} soft target header.stamp is required (doc 02)",
        )

    input_age = value.received_at.seconds - value.input_stamp.seconds
    if input_age < 0.0 or input_age > config.target_input_stale_timeout:
        return (
            None,
            TargetResult.REJECTED_TIMESTAMP,
            f"{side.value} soft target input timestamp is stale or in the future",
        )

    return target, TargetResult.SENT, "accepted"
