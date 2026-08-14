"""Pure single-finger IK objective, analytic gradient and candidate validity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

from .coupling import CouplingModel


class FingerKinematics(Protocol):
    def tip_position_and_jacobian(
        self, full_q: np.ndarray, tip_frame: str
    ) -> tuple[np.ndarray, np.ndarray]: ...


@dataclass(frozen=True)
class FingerProblem:
    active_indices: tuple[int, ...]
    tip_frame: str
    robot_length: float
    target: np.ndarray
    lower: np.ndarray
    upper: np.ndarray


@dataclass(frozen=True)
class CandidateEvidence:
    active: np.ndarray | None
    residual: float
    valid: bool
    solver_usable: bool
    solver_result_code: int
    evaluations: int


def objective_and_gradient(
    active_finger: Sequence[float],
    problem: FingerProblem,
    coupling: CouplingModel,
    kinematics: FingerKinematics,
) -> tuple[float, np.ndarray, float]:
    """Evaluate normalized squared residual and ``J_pinocchio @ B`` gradient."""
    active = np.asarray(active_finger, dtype=np.float64)
    full = np.zeros(10, dtype=np.float64)
    full[list(problem.active_indices)] = active
    full_state = coupling.evaluate(full)
    coupling_jacobian = coupling.jacobian(full)[:, list(problem.active_indices)]
    position, full_jacobian = kinematics.tip_position_and_jacobian(full_state, problem.tip_frame)
    position = np.asarray(position, dtype=np.float64)
    jacobian = np.asarray(full_jacobian, dtype=np.float64)
    if jacobian.shape[0] != 3 or jacobian.shape[1] != 16:
        raise ValueError("Pinocchio tip Jacobian must be the complete 3x16 translation Jacobian")
    error = position - problem.target
    residual = float(np.linalg.norm(error) / problem.robot_length)
    gradient = (2.0 / problem.robot_length ** 2) * (jacobian @ coupling_jacobian).T @ error
    return float(residual * residual), gradient, residual


def validate_candidate(
    active: Sequence[float] | None,
    problem: FingerProblem,
    coupling: CouplingModel,
    kinematics: FingerKinematics,
    solver_usable: bool,
    solver_result_code: int,
    evaluations: int,
    residual_threshold: float,
) -> CandidateEvidence:
    if active is None:
        return CandidateEvidence(
            None, float("nan"), False, solver_usable, solver_result_code, evaluations
        )
    candidate = np.asarray(active, dtype=np.float64)
    if candidate.shape != problem.lower.shape or not np.all(np.isfinite(candidate)):
        return CandidateEvidence(
            candidate,
            float("nan"),
            False,
            solver_usable,
            solver_result_code,
            evaluations,
        )
    if np.any(candidate < problem.lower) or np.any(candidate > problem.upper) or not solver_usable:
        return CandidateEvidence(
            candidate,
            float("nan"),
            False,
            solver_usable,
            solver_result_code,
            evaluations,
        )
    try:
        _, _, residual = objective_and_gradient(candidate, problem, coupling, kinematics)
    except (ValueError, FloatingPointError):
        return CandidateEvidence(
            candidate,
            float("nan"),
            False,
            solver_usable,
            solver_result_code,
            evaluations,
        )
    return CandidateEvidence(
        candidate,
        residual,
        residual <= residual_threshold and np.isfinite(residual),
        solver_usable,
        solver_result_code,
        evaluations,
    )
