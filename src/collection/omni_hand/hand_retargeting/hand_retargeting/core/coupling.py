"""Pure active-to-full O10 coupling and analytic Jacobian."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from omnihand_o10_model.contract import (
    ACTIVE_JOINT_BASES,
    expected_couplings,
    FULL_JOINT_BASES,
    joint_name,
)
from omnihand_o10_model.mjcf_validator import MjcfCouplingModel


def _poly_and_derivative(coef: Sequence[float], value: float) -> tuple[float, float]:
    if len(coef) != 5:
        raise ValueError("coupling polynomial must have five coefficients")
    c0, c1, c2, c3, c4 = (float(item) for item in coef)
    result = (((c4 * value + c3) * value + c2) * value + c1) * value + c0
    derivative = ((4.0 * c4 * value + 3.0 * c3) * value + 2.0 * c2) * value + c1
    return result, derivative


@dataclass(frozen=True)
class CouplingModel:
    """A validated side-specific coupling model used by Core and adapters."""

    side: str
    passive_drivers: tuple[tuple[str, str, tuple[float, ...]], ...]

    @classmethod
    def from_mjcf(cls, model: MjcfCouplingModel) -> "CouplingModel":
        return cls(
            model.side,
            tuple(
                (entry.passive_joint, entry.active_joint, entry.polycoef)
                for entry in model.couplings
            ),
        )

    @classmethod
    def from_contract(cls, side: str) -> "CouplingModel":
        """Build the same representation from a validated pinned contract."""
        return cls(
            side,
            tuple(
                (
                    joint_name(side, spec.passive),
                    joint_name(side, spec.active),
                    spec.polycoef,
                )
                for spec in expected_couplings(side)
            ),
        )

    def evaluate(self, active: Sequence[float]) -> np.ndarray:
        active_arr = np.asarray(active, dtype=np.float64)
        if active_arr.shape != (10,) or not np.all(np.isfinite(active_arr)):
            raise ValueError("active state must be a finite 10-vector")
        active_index = self._active_index()
        active_base_index = {key.split("_", 1)[1].removesuffix("_joint"): value
                             for key, value in active_index.items()}
        passive = {}
        for passive_name, active_name, coef in self.passive_drivers:
            passive[self._base_name(passive_name)] = _poly_and_derivative(
                coef, float(active_arr[active_index[active_name]])
            )[0]
        full = np.empty(16, dtype=np.float64)
        for index, name in enumerate(FULL_JOINT_BASES):
            if name in active_base_index:
                full[index] = active_arr[active_base_index[name]]
            else:
                full[index] = passive[self._base_name(name)]
        return full

    def jacobian(self, active: Sequence[float]) -> np.ndarray:
        """Return ``d(full_q)/d(active_q)`` from the same polynomial data."""
        active_arr = np.asarray(active, dtype=np.float64)
        if active_arr.shape != (10,) or not np.all(np.isfinite(active_arr)):
            raise ValueError("active state must be a finite 10-vector")
        active_index = self._active_index()
        active_base_index = {key.split("_", 1)[1].removesuffix("_joint"): value
                             for key, value in active_index.items()}
        result = np.zeros((16, 10), dtype=np.float64)
        for row, name in enumerate(FULL_JOINT_BASES):
            if name in active_base_index:
                result[row, active_base_index[name]] = 1.0
        for passive_name, active_name, coef in self.passive_drivers:
            active_column = active_index[active_name]
            value = float(active_arr[active_column])
            derivative = _poly_and_derivative(coef, value)[1]
            result[
                FULL_JOINT_BASES.index(self._base_name(passive_name)),
                active_column,
            ] = derivative
        return result

    @staticmethod
    def _base_name(concrete_name: str) -> str:
        if concrete_name.startswith(("L_", "R_")):
            concrete_name = concrete_name.split("_", 1)[1]
        return concrete_name.removesuffix("_joint")

    def _active_index(self) -> dict[str, int]:
        prefix = "L_" if self.side == "left" else "R_"
        return {f"{prefix}{base}_joint": index for index, base in enumerate(ACTIVE_JOINT_BASES)}
