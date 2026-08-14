"""NLopt SLSQP adapter for one bounded finger solve."""

from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from ..core.ik import FingerProblem, objective_and_gradient


class NLoptUnavailableError(RuntimeError):
    """The real NLopt Python bindings are unavailable."""


@dataclass(frozen=True)
class SolverResult:
    candidate: np.ndarray | None
    result_code: int
    evaluations: int
    elapsed_sec: float
    solver_usable: bool


class NloptSlsqpOptimizer:
    """Use NLopt's bounded LD_SLSQP without hiding its stop code."""

    def __init__(self, coupling, kinematics, max_evaluations: int, max_time_sec: float):
        try:
            import nlopt
        except Exception as error:
            raise NLoptUnavailableError(
                "BLOCKED_ENV: nlopt Python bindings are unavailable"
            ) from error
        self._nlopt = nlopt
        self.coupling = coupling
        self.kinematics = kinematics
        self.max_evaluations = max_evaluations
        self.max_time_sec = max_time_sec

    def solve(self, problem: FingerProblem, initial: np.ndarray) -> SolverResult:
        optimizer = self._nlopt.opt(self._nlopt.LD_SLSQP, len(problem.active_indices))
        optimizer.set_lower_bounds(problem.lower.tolist())
        optimizer.set_upper_bounds(problem.upper.tolist())
        optimizer.set_maxeval(self.max_evaluations)
        optimizer.set_maxtime(self.max_time_sec)
        evaluations = 0

        def objective(values, gradient):
            nonlocal evaluations
            evaluations += 1
            loss, analytic, _ = objective_and_gradient(
                values, problem, self.coupling, self.kinematics
            )
            gradient[:] = analytic
            return loss

        optimizer.set_min_objective(objective)
        started = time.perf_counter()
        try:
            candidate = np.asarray(
                optimizer.optimize(np.asarray(initial, dtype=np.float64)),
                dtype=np.float64,
            )
            result_code = int(optimizer.last_optimize_result())
            usable = bool(np.all(np.isfinite(candidate)))
        except Exception:
            candidate = None
            result_code = -1
            usable = False
        return SolverResult(
            candidate, result_code, evaluations, time.perf_counter() - started, usable
        )
