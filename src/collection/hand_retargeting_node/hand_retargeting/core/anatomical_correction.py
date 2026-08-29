"""Pure anatomical corrections applied before robot target construction."""

from __future__ import annotations

from omnihand_o10_contracts import Side

from ..contracts import Vector3


def correct_anatomical_human_vector(
    side: Side, finger_index: int, vector: Vector3
) -> Vector3:
    """
    Apply the shared Rokoko glove lateral convention for both sides.

    The verified O10 palm frames and the observed Rokoko glove encodings
    disagree on the lateral axis for each hand.  The left reflection was
    verified on the real chain (2026-08-20); the right side applies the
    same reflection by symmetry inference (2026-08-29) and is not
    real-machine verified.  Both sides reflect X only and keep the
    longitudinal and palm-normal axes unchanged.
    """
    if not 0 <= finger_index < 5:
        raise ValueError(f"finger_index out of range: {finger_index}")
    return (-vector[0], vector[1], vector[2])
