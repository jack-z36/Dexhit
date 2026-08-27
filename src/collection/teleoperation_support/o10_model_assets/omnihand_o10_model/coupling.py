"""Derive O10 passive joints from active joint variables.

Spec decision 21/23: the six passive joints are not commanded. They are
uniquely derived from the active variables via the MJCF polynomial couplings
recorded by :mod:`omnihand_o10_model.mjcf_validator`. This module evaluates the
polynomials (``passive = poly(active)``) and assembles the 16-dimensional full
kinematic state used for forward kinematics with mimic disabled.

The coupling *evaluation* is a pure function over the pinned polynomial
coefficients; it has no ROS, file-system or pinocchio dependency. The analytic
Jacobian of the coupling map is intentionally NOT provided here: it is owned by
the hand_retargeting Core (``CouplingModel`` analytic-Jacobian API) per the
ARCHITECTURE ownership table.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple, Union

from .contract import (
    ACTIVE_JOINT_BASES,
    FULL_JOINT_BASES,
    PASSIVE_JOINT_BASES,
    expected_couplings,
    side_contract,
)
from .mjcf_validator import MjcfCouplingModel, validate_mjcf_couplings


class CouplingError(Exception):
    """Raised when passive joints cannot be derived from active variables."""


def evaluate_polycoef(
    polycoef: Sequence[float], active_value: float
) -> float:
    """Evaluate ``c0 + c1*a + c2*a**2 + c3*a**3 + c4*a**4``.

    Horner evaluation; raises if the active value is non-finite or the
    coefficient vector is not the 5 finite values defined by the contract.
    """
    if len(polycoef) != 5:
        raise CouplingError(
            f"polycoef must have exactly 5 coefficients, got {len(polycoef)}"
        )
    if not math.isfinite(active_value):
        raise CouplingError(f"active value is not finite: {active_value}")
    c0, c1, c2, c3, c4 = polycoef
    if not all(math.isfinite(c) for c in (c0, c1, c2, c3, c4)):
        raise CouplingError(f"polycoef contains non-finite coefficients: {polycoef}")
    # Horner form: (((c4*a + c3)*a + c2)*a + c1)*a + c0
    result = c4
    for coef in (c3, c2, c1, c0):
        result = result * active_value + coef
    return result


def derive_passive(
    active_values: Sequence[float],
    side: str,
    *,
    coupling_model: Union[MjcfCouplingModel, None] = None,
) -> Tuple[float, ...]:
    """Derive the six passive joint values from the ten active joint values.

    ``active_values`` must be in the fixed command order
    (:data:`omnihand_o10_model.contract.ACTIVE_JOINT_BASES`). The returned
    tuple is in :data:`omnihand_o10_model.contract.PASSIVE_JOINT_BASES` order.
    """
    if len(active_values) != len(ACTIVE_JOINT_BASES):
        raise CouplingError(
            f"expected {len(ACTIVE_JOINT_BASES)} active values, "
            f"got {len(active_values)}"
        )
    contract = side_contract(side)
    active_index = {name: i for i, name in enumerate(contract.active_joints)}

    # Each passive joint is driven by exactly one active joint via a pinned
    # polynomial. Resolve (active_concrete, polycoef) per passive joint,
    # preferring a validated MJCF coupling model (real assets) and falling back
    # to the pinned contract coefficients when none is supplied.
    resolved: list = []
    for spec in expected_couplings(side):
        active_concrete = next(
            j for j in contract.active_joints if j.endswith(spec.active + "_joint")
        )
        passive_concrete = next(
            j for j in contract.passive_joints if j.endswith(spec.passive + "_joint")
        )
        coef = (
            coupling_model.polycoef_for(passive_concrete)
            if coupling_model is not None
            else spec.polycoef
        )
        resolved.append((passive_concrete, active_concrete, coef))

    derived: list = []
    for passive_joint in contract.passive_joints:
        match = [item for item in resolved if item[0] == passive_joint]
        if not match:
            raise CouplingError(
                f"no polynomial coupling for passive joint {passive_joint!r}"
            )
        _, active_concrete, coef = match[0]
        value = active_values[active_index[active_concrete]]
        derived.append(evaluate_polycoef(coef, value))
    return tuple(derived)


def build_full_state(
    active_values: Sequence[float],
    side: str,
    *,
    coupling_model: Union[MjcfCouplingModel, None] = None,
) -> Tuple[float, ...]:
    """Assemble the 16-dim full kinematic state (URDF document order).

    Active joints are placed at their document-order positions; passive joints
    are derived from the active variables via the couplings.
    """
    derived = derive_passive(active_values, side, coupling_model=coupling_model)
    contract = side_contract(side)
    active_map = dict(zip(contract.active_joints, active_values))
    passive_map = dict(zip(contract.passive_joints, derived))

    full: list = []
    for joint in contract.full_joints:
        if joint in active_map:
            full.append(active_map[joint])
        else:
            full.append(passive_map[joint])
    return tuple(full)


def validate_active_value_finite(active_values: Sequence[float]) -> None:
    """Reject non-finite active values before coupling derivation."""
    for index, value in enumerate(active_values):
        if not math.isfinite(value):
            raise CouplingError(
                f"active joint {ACTIVE_JOINT_BASES[index]} has non-finite value {value}"
            )
