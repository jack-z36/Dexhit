"""Model-backed, bounded single-finger target projection primitives."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .coupling import CouplingModel
from .ik import FingerKinematics, FingerProblem


@dataclass(frozen=True)
class ProjectionWitness:
    """A finite, in-bounds active state and its real FK target."""

    active: np.ndarray | None
    target: np.ndarray | None
    distance: float
    available: bool


def build_projection_witness(
    problem: FingerProblem,
    candidate: np.ndarray | None,
    coupling: CouplingModel,
    kinematics: FingerKinematics,
) -> ProjectionWitness:
    """Turn a usable raw-target candidate into a model-observable target.

    This is deliberately not a global nearest-point solver.  The candidate is
    supplied by the existing bounded single-start optimizer; the witness is
    accepted only when coupling and full FK can explain it with finite values.
    """
    if candidate is None:
        return ProjectionWitness(None, None, float("nan"), False)
    active = np.asarray(candidate, dtype=np.float64)
    if (
        active.shape != problem.lower.shape
        or not np.all(np.isfinite(active))
        or np.any(active < problem.lower)
        or np.any(active > problem.upper)
    ):
        return ProjectionWitness(active, None, float("nan"), False)
    full_active = np.zeros(10, dtype=np.float64)
    full_active[list(problem.active_indices)] = active
    try:
        full_state = np.asarray(coupling.evaluate(full_active), dtype=np.float64)
        if full_state.shape != (16,) or not np.all(np.isfinite(full_state)):
            return ProjectionWitness(active, None, float("nan"), False)
        target, _ = kinematics.tip_position_and_jacobian(full_state, problem.tip_frame)
        target = np.asarray(target, dtype=np.float64)
        if target.shape != (3,) or not np.all(np.isfinite(target)):
            return ProjectionWitness(active, None, float("nan"), False)
    except (ValueError, FloatingPointError, TypeError):
        return ProjectionWitness(active, None, float("nan"), False)
    distance = float(np.linalg.norm(np.asarray(problem.target) - target) / problem.robot_length)
    if not np.isfinite(distance):
        return ProjectionWitness(active, None, float("nan"), False)
    return ProjectionWitness(active, target, distance, True)
