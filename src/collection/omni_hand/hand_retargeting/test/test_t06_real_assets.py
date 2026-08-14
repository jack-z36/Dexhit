"""Real O10 asset gradient verification for T06.

The test is intentionally opt-in: the model assets remain an external,
read-only fixture until their redistribution licence is confirmed.  When the
fixture path and the dedicated Python environment are supplied, this test
checks both the Pinocchio translation Jacobian and the complete objective
gradient for every side and finger.
"""

from __future__ import annotations

import importlib.util
import os

from hand_retargeting.adapters.pinocchio import PinocchioFingerKinematics
from hand_retargeting.application.session import FINGER_ACTIVE_INDICES, FINGER_TIP_BASES
from hand_retargeting.core.coupling import CouplingModel
from hand_retargeting.core.ik import FingerProblem, objective_and_gradient
import numpy as np
from omnihand_o10_contracts import JOINT_LIMITS
from omnihand_o10_model import load_model
from omnihand_o10_model.contract import tip_link
import pytest


if not os.environ.get("OMNIHAND_O10_MODEL_FIXTURE"):
    pytest.skip(
        "T06 real-asset verification requires OMNIHAND_O10_MODEL_FIXTURE",
        allow_module_level=True,
    )
if importlib.util.find_spec("pinocchio") is None:
    pytest.skip("T06 real-asset verification requires pinocchio", allow_module_level=True)
if importlib.util.find_spec("nlopt") is None:
    pytest.skip("T06 real-asset verification requires nlopt", allow_module_level=True)


def _central_difference(function, value: np.ndarray, epsilon: float) -> np.ndarray:
    result = np.empty((3, value.size), dtype=np.float64)
    for index in range(value.size):
        plus = value.copy()
        minus = value.copy()
        plus[index] += epsilon
        minus[index] -= epsilon
        result[:, index] = (function(plus) - function(minus)) / (2.0 * epsilon)
    return result


@pytest.mark.parametrize("side", ("left", "right"))
def test_real_pinocchio_tip_jacobian_matches_central_difference_for_all_fingers(side):
    assets = load_model()[side]
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    limits = JOINT_LIMITS[side]
    active = np.asarray(
        [(lower + upper) / 2.0 for lower, upper in zip(limits.lower, limits.upper)],
        dtype=np.float64,
    )
    full = coupling.evaluate(active)

    for tip_base in FINGER_TIP_BASES:
        frame = tip_link(side, tip_base)

        def position(state):
            return kinematics.tip_position_and_jacobian(state, frame)[0]

        _, analytic = kinematics.tip_position_and_jacobian(full, frame)
        numeric = _central_difference(position, full, 1e-7)
        np.testing.assert_allclose(analytic, numeric, rtol=2e-5, atol=2e-7)


@pytest.mark.parametrize("side", ("left", "right"))
def test_real_objective_gradient_matches_central_difference_for_all_fingers(side):
    assets = load_model()[side]
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    limits = JOINT_LIMITS[side]
    active = np.asarray(
        [(lower + upper) / 2.0 for lower, upper in zip(limits.lower, limits.upper)],
        dtype=np.float64,
    )
    full = coupling.evaluate(active)

    for tip_base, active_indices in zip(FINGER_TIP_BASES, FINGER_ACTIVE_INDICES):
        frame = tip_link(side, tip_base)
        origin = kinematics.tip_position_and_jacobian(full, frame)[0]
        problem = FingerProblem(
            active_indices=active_indices,
            tip_frame=frame,
            robot_length=1.0,
            target=origin + np.asarray((1e-3, -5e-4, 3e-4)),
            lower=np.asarray([limits.lower[index] for index in active_indices]),
            upper=np.asarray([limits.upper[index] for index in active_indices]),
        )
        finger_active = active[list(active_indices)]
        _, analytic, _ = objective_and_gradient(
            finger_active, problem, coupling, kinematics
        )

        def loss(value):
            candidate = active.copy()
            candidate[list(active_indices)] = value
            full_candidate = coupling.evaluate(candidate)
            position = kinematics.tip_position_and_jacobian(full_candidate, frame)[0]
            error = position - problem.target
            return float(error @ error)

        numeric = np.empty_like(finger_active)
        epsilon = 1e-7
        for index in range(finger_active.size):
            plus = finger_active.copy()
            minus = finger_active.copy()
            plus[index] += epsilon
            minus[index] -= epsilon
            numeric[index] = (loss(plus) - loss(minus)) / (2.0 * epsilon)
        np.testing.assert_allclose(analytic, numeric, rtol=3e-5, atol=3e-7)
