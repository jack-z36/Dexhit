"""Pure anatomical corrections applied before robot target construction."""

from __future__ import annotations

from omnihand_o10_contracts import Side

from ..contracts import Vector3


def correct_anatomical_human_vector(
    side: Side, finger_index: int, vector: Vector3
) -> Vector3:
    """Correct left palm lateral semantics while preserving normal/longitudinal axes."""
    if not 0 <= finger_index < 5:
        raise ValueError(f"finger_index out of range: {finger_index}")
    if side is Side.LEFT:
        return (-vector[0], vector[1], vector[2])
    return vector
