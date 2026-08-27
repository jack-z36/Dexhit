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

from hand_retargeting.adapters.model_geometry import load_robot_geometry
from hand_retargeting.adapters.nlopt import NloptSlsqpOptimizer
from hand_retargeting.adapters.pinocchio import PinocchioFingerKinematics
from hand_retargeting.application.session import (
    FINGER_ACTIVE_INDICES,
    FINGER_TIP_BASES,
    RetargetingSession,
)
from hand_retargeting.contracts import RawHandFrameValue, RetargetingConfig
from hand_retargeting.core.coupling import CouplingModel
from hand_retargeting.core.ik import FingerProblem, objective_and_gradient, validate_candidate
import numpy as np
from omnihand_o10_contracts import JOINT_LIMITS, Side
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


def test_real_reachable_thumb_roundoff_keeps_candidate_for_validation():
    """A real optimum may stop with NLopt roundoff; validity remains separate."""
    side = "right"
    assets = load_model()[side]
    geometry = load_robot_geometry(side)
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    limits = JOINT_LIMITS[side]
    active_indices = FINGER_ACTIVE_INDICES[0]
    lower = np.asarray([limits.lower[index] for index in active_indices])
    upper = np.asarray([limits.upper[index] for index in active_indices])
    reachable_active = np.zeros(10, dtype=np.float64)
    reachable_active[list(active_indices)] = lower + 0.2 * (upper - lower)
    frame = tip_link(side, FINGER_TIP_BASES[0])
    target = kinematics.tip_position_and_jacobian(
        coupling.evaluate(reachable_active), frame
    )[0]
    problem = FingerProblem(
        active_indices=active_indices,
        tip_frame=frame,
        robot_length=geometry.finger_chain_lengths[0],
        target=target,
        lower=lower,
        upper=upper,
    )
    optimizer = NloptSlsqpOptimizer(coupling, kinematics, 250, 0.25)
    result = optimizer.solve(problem, (lower + upper) / 2.0)
    evidence = validate_candidate(
        result.candidate,
        problem,
        coupling,
        kinematics,
        result.solver_usable,
        result.result_code,
        result.evaluations,
        0.05,
    )

    assert result.candidate is not None
    assert result.solver_usable is True
    assert evidence.valid is True
    assert evidence.residual == pytest.approx(0.0, abs=1e-7)


def test_real_unreachable_thumb_projects_to_fk_target_and_keeps_validity_gate():
    """A raw unreachable target is replaced only after FK-backed validation."""
    side = "right"
    assets = load_model()[side]
    geometry = load_robot_geometry(side)
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    config = RetargetingConfig(
        1e-6, 1e-6, 1e-6, 3, 2,
        (0.01,) * 5, (0.10,) * 5, (0.05,) * 5,
        250, 0.25, (0.1,) * 10, 0.5, 2, 0.1, 0.5,
    )
    suffixes = (
        "Hand", "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    positions = [(0.0, 0.0, 0.0)]
    for x in (0.8, 0.6, 0.2, -0.2, -0.6):
        positions.extend(
            [(x, 1.0, 0.0), (x, 1.4, 0.0), (x, 1.8, 0.0), (x, 2.2, 0.0)]
        )
    frame = RawHandFrameValue(
        tuple("right" + suffix for suffix in suffixes),
        tuple(positions),
        1,
    )
    session = RetargetingSession(
        Side.RIGHT, config, geometry, coupling=coupling,
        kinematics=kinematics,
        optimizer=NloptSlsqpOptimizer(coupling, kinematics, 250, 0.25),
    )
    for stamp in range(1, 6):
        decision = session.process(
            RawHandFrameValue(frame.node_names, frame.positions, stamp)
        )

    assert decision.ik_state[0] == "valid"
    assert decision.has_valid_ik == (True,) * 5
    assert decision.target_projection_applied[0] is True
    assert decision.target_projection_distance_available[0] is True
    assert decision.normalized_target_projection_distance[0] > 0.0
    assert decision.command_published is True


def test_real_left_pip_commands_follow_palm_flexion_direction():
    """A left-hand palm flexion step must increase all four O10 PIP commands.

    The expected direction comes from the verified O10 convention: positive
    index/middle/ring/pinky PIP is toward the palm.  Human frames are small,
    deterministic canonical 21-node fixtures whose normalized fingertip
    directions are generated from the real model's FK targets.
    """
    side = "left"
    assets = load_model()[side]
    geometry = load_robot_geometry(side)
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    limits = JOINT_LIMITS[side]
    config = RetargetingConfig(
        1e-6, 1e-6, 1e-6, 3, 2,
        (0.01,) * 5, (0.10,) * 5, (0.05,) * 5,
        500, 0.5, (0.1,) * 10, 0.5, 3, 0.1, 0.5,
    )
    optimizer = NloptSlsqpOptimizer(coupling, kinematics, 500, 0.5)
    session = RetargetingSession(
        Side.LEFT, config, geometry, coupling=coupling,
        kinematics=kinematics, optimizer=optimizer,
    )

    baseline = np.asarray(
        [lower + 0.15 * (upper - lower)
         for lower, upper in zip(limits.lower, limits.upper)],
        dtype=np.float64,
    )
    flexed = baseline.copy()
    flexed[[4, 5, 7, 9]] += 0.08

    suffixes = (
        "Hand", "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    roots_x = (0.8, 0.6, 0.2, -0.2, -0.6)
    raw_roots = ((0.0, 0.0, 0.0),) + tuple(
        (x, 1.0, 0.0) for x in roots_x
    )

    def frame_for(active, stamp):
        full = coupling.evaluate(active)
        positions = [raw_roots[0]]
        for finger_index, tip_base in enumerate(FINGER_TIP_BASES):
            tip_frame = tip_link(side, tip_base)
            tip = kinematics.tip_position_and_jacobian(
                full, tip_frame
            )[0]
            delta = np.asarray(tip) - np.asarray(geometry.finger_roots[finger_index])
            robot_direction = delta / np.linalg.norm(delta)
            # The production target path applies geometry.direction_mapping
            # after entering the anatomical palm frame.  Generate the raw
            # fixture in the independent inverse direction so the expected
            # target is the verified FK direction under the corrected basis.
            direction = np.asarray(geometry.direction_mapping).T @ robot_direction
            for fraction in (0.0, 1 / 3, 2 / 3, 1.0):
                root = np.asarray(raw_roots[finger_index + 1])
                point = root + fraction * direction
                positions.append(tuple(float(value) for value in point))
        return RawHandFrameValue(
            tuple(side + suffix for suffix in suffixes), tuple(positions), stamp
        )

    for stamp in (1_000_000_000, 1_100_000_000, 1_200_000_000, 1_300_000_000):
        baseline_decision = session.process(frame_for(baseline, stamp))
    assert baseline_decision.command_published is True

    flexed_decision = session.process(frame_for(flexed, 1_400_000_000))
    assert flexed_decision.command_published is True
    assert flexed_decision.command_positions is not None
    assert baseline_decision.command_positions is not None
    for index in (4, 5, 7, 9):
        actual = flexed_decision.command_positions[index]
        expected = baseline_decision.command_positions[index]
        assert actual > expected, (
            f"PIP index {index}: baseline={baseline_decision.command_positions[index]!r}, "
            f"flexed={flexed_decision.command_positions[index]!r}, "
            f"baseline_ik={baseline_decision.ik_state!r}, "
            f"flexed_ik={flexed_decision.ik_state!r}, "
            f"baseline_residual={baseline_decision.normalized_residual!r}, "
            f"flexed_residual={flexed_decision.normalized_residual!r}"
        )


def _real_left_direction_session():
    """Build the deterministic real-model session used by direction tests."""
    side = "left"
    assets = load_model()[side]
    geometry = load_robot_geometry(side)
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    config = RetargetingConfig(
        1e-6, 1e-6, 1e-6, 3, 2,
        (0.01,) * 5, (0.10,) * 5, (0.05,) * 5,
        500, 0.5, (0.1,) * 10, 0.5, 3, 0.1, 0.5,
    )
    session = RetargetingSession(
        Side.LEFT, config, geometry, coupling=coupling,
        kinematics=kinematics,
        optimizer=NloptSlsqpOptimizer(coupling, kinematics, 500, 0.5),
    )
    return geometry, kinematics, coupling, session


def _left_frame_for_real_active(
    active, stamp, geometry, kinematics, coupling, human_directions=None
):
    """Create a canonical frame whose palm-frame directions target real FK."""
    suffixes = (
        "Hand", "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    roots_x = (0.8, 0.6, 0.2, -0.2, -0.6)
    raw_roots = ((0.0, 0.0, 0.0),) + tuple(
        (x, 1.0, 0.0) for x in roots_x
    )
    mapping = np.asarray(geometry.direction_mapping)
    full = None if active is None else coupling.evaluate(active)
    positions = [raw_roots[0]]
    human_direction_values = []
    robot_tips = []
    for finger_index, tip_base in enumerate(FINGER_TIP_BASES):
        if human_directions is None:
            tip = kinematics.tip_position_and_jacobian(
                full, tip_link("left", tip_base)
            )[0]
            root = np.asarray(geometry.finger_roots[finger_index])
            robot_direction = (np.asarray(tip) - root)
            robot_direction /= np.linalg.norm(robot_direction)
            human_direction = mapping.T @ robot_direction
            # This helper is inverse-generated from the verified O10 model.
            # RetargetingSession applies the left anatomical X correction
            # before mapping, so the synthetic human fixture must invert it.
            human_direction[0] *= -1.0
        else:
            human_direction = np.asarray(human_directions[finger_index])
            human_direction /= np.linalg.norm(human_direction)
        human_direction_values.append(human_direction)
        if full is not None:
            robot_tips.append(np.asarray(tip))
        raw_root = np.asarray(raw_roots[finger_index + 1])
        for fraction in (0.0, 1 / 3, 2 / 3, 1.0):
            positions.append(tuple(raw_root + fraction * human_direction))
    frame = RawHandFrameValue(
        tuple("left" + suffix for suffix in suffixes), tuple(positions), stamp
    )
    return frame, tuple(human_direction_values), tuple(robot_tips)


def _track_real_left_pair(before, after):
    geometry, kinematics, coupling, session = _real_left_direction_session()
    baseline_frame, baseline_human, baseline_tip = _left_frame_for_real_active(
        before, 1_000_000_000, geometry, kinematics, coupling
    )
    for stamp in (1_000_000_000, 1_100_000_000, 1_200_000_000, 1_300_000_000):
        baseline_frame, baseline_human, baseline_tip = _left_frame_for_real_active(
            before, stamp, geometry, kinematics, coupling
        )
        baseline_decision = session.process(baseline_frame)
    after_frame, after_human, after_target_tip = _left_frame_for_real_active(
        after, 1_400_000_000, geometry, kinematics, coupling
    )
    after_decision = session.process(after_frame)
    assert baseline_decision.command_published is True
    assert after_decision.command_published is True
    assert baseline_decision.command_positions is not None
    assert after_decision.command_positions is not None
    assert baseline_decision.has_valid_ik == (True,) * 5
    assert after_decision.has_valid_ik == (True,) * 5
    for applied, available, distance in zip(
        after_decision.target_projection_applied,
        after_decision.target_projection_distance_available,
        after_decision.normalized_target_projection_distance,
    ):
        assert available is True
        if applied:
            assert distance > 0.0
        else:
            assert distance == pytest.approx(0.0)
    assert all(
        np.isfinite(residual) and residual <= 0.05
        for residual in after_decision.normalized_residual
    )
    limits = JOINT_LIMITS[Side.LEFT]
    after_command = np.asarray(after_decision.command_positions)
    assert limits.contains(after_command)
    return (
        geometry, kinematics, coupling, baseline_decision, after_decision,
        baseline_human, after_human, baseline_tip, after_target_tip,
    )


def _track_real_left_human_pair(before_human, after_human):
    geometry, kinematics, coupling, session = _real_left_direction_session()
    for stamp in (1_000_000_000, 1_100_000_000, 1_200_000_000, 1_300_000_000):
        baseline_frame, _, _ = _left_frame_for_real_active(
            None, stamp, geometry, kinematics, coupling,
            human_directions=before_human,
        )
        baseline_decision = session.process(baseline_frame)
    after_frame, _, _ = _left_frame_for_real_active(
        None, 1_400_000_000, geometry, kinematics, coupling,
        human_directions=after_human,
    )
    after_decision = session.process(after_frame)
    assert baseline_decision.command_published is True
    assert after_decision.command_published is True
    assert baseline_decision.command_positions is not None
    assert after_decision.command_positions is not None
    assert after_decision.has_valid_ik == (True,) * 5
    for applied, available, distance in zip(
        after_decision.target_projection_applied,
        after_decision.target_projection_distance_available,
        after_decision.normalized_target_projection_distance,
    ):
        assert available is True
        if applied:
            assert distance > 0.0
        else:
            assert distance == pytest.approx(0.0)
    assert all(
        np.isfinite(residual) and residual <= 0.05
        for residual in after_decision.normalized_residual
    )
    assert JOINT_LIMITS[Side.LEFT].contains(
        np.asarray(after_decision.command_positions)
    )
    return geometry, kinematics, coupling, baseline_decision, after_decision


def _nearest_left_finger_grid_target(target, finger_index, geometry, kinematics, coupling):
    """Find a deterministic nearest FK point over the bounded active grid."""
    import itertools

    limits = JOINT_LIMITS[Side.LEFT]
    active_indices = FINGER_ACTIVE_INDICES[finger_index]
    axes = [
        np.linspace(limits.lower[index], limits.upper[index], 41)
        for index in active_indices
    ]
    best = None
    for values in itertools.product(*axes):
        active = np.zeros(10, dtype=np.float64)
        active[list(active_indices)] = values
        tip = kinematics.tip_position_and_jacobian(
            coupling.evaluate(active),
            tip_link("left", FINGER_TIP_BASES[finger_index]),
        )[0]
        distance = float(np.linalg.norm(np.asarray(tip) - target))
        if best is None or distance < best[0]:
            best = (distance, tuple(float(value) for value in values), np.asarray(tip))
    assert best is not None
    return best


def test_synthetic_left_thumb_inward_mapping_is_fk_self_consistent():
    """Inverse-mapping synthetic thumb target remains FK self-consistent.

    This fixture is generated from O10 FK and the current mapping; it verifies
    model/mapping self-consistency only, not independent Rokoko thumb semantics.
    """
    limits = JOINT_LIMITS[Side.LEFT]
    baseline = np.asarray(
        [lower + 0.25 * (upper - lower)
         for lower, upper in zip(limits.lower, limits.upper)],
        dtype=np.float64,
    )
    inward = baseline.copy()
    inward[[0, 1, 2]] -= 0.08
    (
        geometry, kinematics, coupling, before, after, _, _, before_tip, _
    ) = _track_real_left_pair(baseline, inward)
    before_q = coupling.evaluate(np.asarray(before.command_positions))
    after_q = coupling.evaluate(np.asarray(after.command_positions))
    before_fk = kinematics.tip_position_and_jacobian(
        before_q, tip_link("left", "thumb_tip")
    )[0]
    after_fk = kinematics.tip_position_and_jacobian(
        after_q, tip_link("left", "thumb_tip")
    )[0]
    palm_center = np.mean(np.asarray(geometry.finger_roots[1:]), axis=0)
    toward_palm = palm_center - before_fk
    displacement = np.asarray(after_fk) - np.asarray(before_fk)

    assert np.dot(displacement, toward_palm) > 0.0
    assert np.linalg.norm(after_fk - palm_center) < np.linalg.norm(
        before_fk - palm_center
    )
    assert np.linalg.norm(before_fk - before_tip[0]) < 0.02
    assert after.residual_available == (True,) * 5


def test_real_left_four_finger_upward_direction_matches_bounded_fk_target():
    """Human palm -Z hand-back motion selects bounded extension."""
    before_human = ((0.0, 1.0, 0.0),) * 5
    upward = np.asarray((0.0, 1.0, -0.35), dtype=np.float64)
    upward /= np.linalg.norm(upward)
    after_human = (tuple(float(value) for value in upward),) * 5
    geometry, kinematics, coupling, before, after = _track_real_left_human_pair(
        before_human, after_human
    )
    before_q = coupling.evaluate(np.asarray(before.command_positions))
    after_q = coupling.evaluate(np.asarray(after.command_positions))
    mapping = np.asarray(geometry.direction_mapping)
    for finger_index, pip_index, coordinate_label in zip(
        (1, 2, 3, 4), (4, 5, 7, 9),
        ("index_abad+pip", "middle_pip_only", "ring_abad+pip", "pinky_abad+pip")
    ):
        assert after_human[finger_index][2] < before_human[finger_index][2]
        root = np.asarray(geometry.finger_roots[finger_index])
        target = root + geometry.finger_chain_lengths[finger_index] * (
            mapping @ np.asarray(after_human[finger_index])
        )
        nearest_distance, nearest_values, nearest_tip = _nearest_left_finger_grid_target(
            target, finger_index, geometry, kinematics, coupling
        )
        before_fk = kinematics.tip_position_and_jacobian(
            before_q, tip_link("left", FINGER_TIP_BASES[finger_index])
        )[0]
        after_fk = kinematics.tip_position_and_jacobian(
            after_q, tip_link("left", FINGER_TIP_BASES[finger_index])
        )[0]
        before_distance = float(np.linalg.norm(before_fk - target))
        after_distance = float(np.linalg.norm(after_fk - target))
        pip_step = (
            float(JOINT_LIMITS[Side.LEFT].upper[pip_index])
            - float(JOINT_LIMITS[Side.LEFT].lower[pip_index])
        ) / 40.0
        assert after.command_positions[pip_index] <= (
            before.command_positions[pip_index] + 1e-9
        ), (
            f"finger {finger_index} PIP {pip_index} increased for upward input; "
            f"group={coordinate_label}, before={before.command_positions[pip_index]!r}, "
            f"after={after.command_positions[pip_index]!r}, "
            f"nearest_grid_pip={nearest_values[-1]!r}"
        )
        assert abs(after.command_positions[pip_index] - nearest_values[-1]) <= (
            0.5 * pip_step
        )
        assert after_distance <= before_distance + 1e-9
        assert after_distance <= nearest_distance + 0.5 * pip_step
        assert np.linalg.norm(after_fk - target) <= np.linalg.norm(
            nearest_tip - target
        ) + 0.5 * pip_step
    assert all(np.isfinite(value) for value in after.normalized_residual)
