"""T06 pure seams: coupling, IK evidence, application and smoothing."""

from dataclasses import dataclass

from hand_retargeting.adapters.nlopt import NLoptUnavailableError
from hand_retargeting.adapters.pinocchio import PinocchioUnavailableError
from hand_retargeting.application.session import RetargetingSession
from hand_retargeting.contracts import RawHandFrameValue, RetargetingConfig
from hand_retargeting.core.coupling import CouplingModel
from hand_retargeting.core.ik import FingerProblem, objective_and_gradient
from hand_retargeting.core.ik import validate_candidate
from hand_retargeting.core.normalization import RobotHandGeometry
from hand_retargeting.core.projection import build_projection_witness
import numpy as np
from omnihand_o10_contracts import JOINT_LIMITS, Side
import pytest


def _config(**changes):
    values = {
        "palm_y_epsilon": 1e-6,
        "palm_x_epsilon": 1e-6,
        "finger_length_epsilon": 1e-6,
        "length_window_size": 3,
        "stable_window_count": 2,
        "length_nmad_thresholds": (0.01,) * 5,
        "frozen_length_relative_thresholds": (0.10,) * 5,
        "ik_residual_thresholds": (100.0,) * 5,
        "ik_max_evaluations": 10,
        "ik_max_time_sec": 0.01,
        "smooth_time_constants": (0.1,) * 10,
        "stale_timeout_sec": 0.5,
        "recovery_min_valid_frames": 2,
        "recovery_min_duration_sec": 0.1,
        "recovery_confirmation_timeout_sec": 0.5,
    }
    values.update(changes)
    return RetargetingConfig(**values)


def _frame(stamp, side=Side.RIGHT):
    suffixes = (
        "Hand", "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    roots = (0.8, 0.6, 0.2, -0.2, -0.6)
    positions = [(0.0, 0.0, 0.0)]
    for x in roots:
        positions.extend([(x, 1.0, 0.0), (x, 1.4, 0.0), (x, 1.8, 0.0), (x, 2.2, 0.0)])
    return RawHandFrameValue(
        tuple(side.value + suffix for suffix in suffixes), tuple(positions), stamp
    )


def _geometry():
    return RobotHandGeometry(
        tuple((float(i), 0.0, 0.0) for i in range(5)), (2.0, 3.0, 4.0, 5.0, 6.0),
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )


class _Kinematics:
    def tip_position_and_jacobian(self, full_q, tip_frame):
        # A deterministic full-state Jacobian; the objective still has to
        # multiply it by the full 16x10 coupling Jacobian.
        return np.array([full_q[0], full_q[1], full_q[2]]), np.pad(
            np.eye(3, 3), ((0, 0), (0, 13))
        )


@dataclass
class _Result:
    candidate: np.ndarray
    result_code: int = 5
    evaluations: int = 7
    elapsed_sec: float = 0.002
    solver_usable: bool = True


class _Optimizer:
    def __init__(self, candidates=None):
        self.initials = []
        self.candidates = candidates
        self.fail = False

    def solve(self, problem, initial):
        self.initials.append(np.asarray(initial).copy())
        if self.fail:
            return _Result(None, solver_usable=False)
        candidate = np.asarray(initial if self.candidates is None else self.candidates.pop(0))
        return _Result(candidate)


class _ProjectionKinematics:
    def tip_position_and_jacobian(self, full_q, tip_frame):
        return np.asarray(full_q[:3], dtype=float), np.zeros((3, 16))


def _projection_problem(target):
    return FingerProblem(
        (0, 1, 2), "R_thumb_tip", 1.0, np.asarray(target, dtype=float),
        np.full(3, -1.0), np.full(3, 1.0),
    )


@pytest.mark.parametrize(
    "raw_target", ((0.0, 0.0, 2.0), (0.0, 0.0, -2.0), (2.0, 0.0, 0.0)),
    ids=("A-dir", "A-under", "A-ext"),
)
def test_projection_witness_keeps_raw_invalid_and_accepts_fk_projected_target(raw_target):
    coupling = CouplingModel.from_contract("right")
    kinematics = _ProjectionKinematics()
    problem = _projection_problem(raw_target)
    candidate = np.array((0.25, -0.25, 0.5))

    raw = validate_candidate(
        candidate, problem, coupling, kinematics, True, 5, 3, 0.05
    )
    witness = build_projection_witness(problem, candidate, coupling, kinematics)
    projected_evidence = validate_candidate(
        witness.active, _projection_problem(witness.target), coupling,
        kinematics, True, 5, 3, 0.05,
    )

    assert raw.valid is False
    assert witness.available is True
    assert witness.target == pytest.approx(candidate)
    assert witness.distance == pytest.approx(np.linalg.norm(
        np.asarray(raw_target) - candidate
    ))
    assert projected_evidence.valid is True
    assert projected_evidence.residual == pytest.approx(0.0)


def test_projection_witness_rejects_nonfinite_candidate():
    witness = build_projection_witness(
        _projection_problem((0.0, 0.0, 1.0)), np.array((np.nan, 0.0, 0.0)),
        CouplingModel.from_contract("right"), _ProjectionKinematics(),
    )
    assert witness.available is False
    assert np.isnan(witness.distance)


def test_coupling_jacobian_matches_independent_central_difference():
    model = CouplingModel.from_contract("right")
    active = np.array([0.2, -0.3, 0.4, -0.1, 0.7, 0.5, 0.1, 0.8, 0.04, 0.9])
    analytic = model.jacobian(active)
    epsilon = 1e-6
    numeric = np.column_stack([
        (model.evaluate(active + np.eye(10)[i] * epsilon)
         - model.evaluate(active - np.eye(10)[i] * epsilon)) / (2 * epsilon)
        for i in range(10)
    ])
    assert analytic == pytest.approx(numeric, abs=1e-7)


def test_ik_gradient_is_pinocchio_full_translation_jacobian_times_coupling():
    model = CouplingModel.from_contract("right")
    problem = FingerProblem((0, 1, 2), "R_thumb_tip", 2.0,
                            np.array([0.1, 0.2, 0.3]),
                            np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]))
    loss, gradient, residual = objective_and_gradient(
        np.array([0.2, -0.3, 0.4]), problem, model, _Kinematics()
    )
    assert loss == pytest.approx(residual ** 2)
    assert gradient.shape == (3,)
    assert np.all(np.isfinite(gradient))


def test_session_uses_midpoint_then_previous_valid_warm_start_and_holds_failure():
    optimizer = _Optimizer()
    session = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=optimizer,
    )
    for stamp in (1, 2, 3, 4):
        first = session.process(_frame(stamp))
    assert first.all_lengths_frozen
    midpoint = optimizer.initials[0]
    limits = JOINT_LIMITS[Side.RIGHT]
    expected_midpoint = np.array(
        [(limits.lower[index] + limits.upper[index]) / 2 for index in (0, 1, 2)]
    )
    assert midpoint == pytest.approx(expected_midpoint)
    second = session.process(_frame(5))
    assert optimizer.initials[5] == pytest.approx(midpoint)
    assert second.command_published is True
    optimizer.fail = True
    held = session.process(_frame(6))
    assert all(held.used_previous_valid_target)
    assert held.command_published is True


def test_low_pass_uses_receive_stamp_not_wall_clock():
    optimizer = _Optimizer()
    session = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=optimizer,
    )
    for stamp in (1_000_000_000, 1_100_000_000, 1_200_000_000, 1_300_000_000):
        session.process(_frame(stamp))
    assert session._filter.last_stamp_ns == 1_300_000_000


def test_stale_recovery_requires_contiguous_frames_and_holds_before_following():
    session = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=_Optimizer(),
    )
    for stamp in (1, 2, 3, 4, 5):
        tracked = session.process(_frame(stamp))
    held_target = tracked.command_positions
    assert tracked.phase == "tracking"
    assert session.mark_stale().command_published is False
    confirming = session.process(_frame(1_000_000_000))
    assert confirming.stale is True
    assert confirming.phase == "recovery-confirming"
    assert confirming.recovery_valid_count == 1
    assert confirming.command_published is False
    resumed = session.process(_frame(1_100_000_000))
    assert resumed.phase == "recovery-resuming"
    assert resumed.command_published is True
    assert resumed.command_positions == pytest.approx(held_target)


def test_stale_recovery_times_out_to_stale_and_restarts_confirmation_window():
    optimizer = _Optimizer()
    session = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=optimizer,
    )
    for stamp in (1, 2, 3, 4, 5):
        session.process(_frame(stamp))
    session.mark_stale()

    first = session.process(_frame(1_000_000_000))
    assert first.phase == "recovery-confirming"
    assert first.recovery_valid_count == 1
    optimizer.fail = True
    timed_out = session.process(_frame(1_600_000_001))
    assert timed_out.phase == "stale"
    assert timed_out.stale is True
    assert timed_out.command_published is False
    assert all(timed_out.has_valid_ik) is False
    assert timed_out.recovery_valid_count == 0
    assert timed_out.recovery_valid_duration_sec == 0.0

    optimizer.fail = False
    restarted = session.process(_frame(2_000_000_000))
    assert restarted.phase == "recovery-confirming"
    assert restarted.recovery_valid_count == 1


def test_recovery_timeout_attempt_start_survives_invalid_frames():
    optimizer = _Optimizer()
    session = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=optimizer,
    )
    for stamp in (1, 2, 3, 4, 5):
        session.process(_frame(stamp))
    session.mark_stale()
    optimizer.fail = True
    first = session.process(_frame(1_000_000_000))
    assert first.phase == "recovery-confirming"
    still_confirming = session.process(_frame(1_400_000_000))
    assert still_confirming.phase == "recovery-confirming"
    timed_out = session.process(_frame(1_600_000_001))
    assert timed_out.phase == "stale"
    assert timed_out.recovery_valid_count == 0


def test_t06_side_aggregates_do_not_share_ik_or_filter_history():
    left = RetargetingSession(
        Side.LEFT, _config(), _geometry(), coupling=CouplingModel.from_contract("left"),
        kinematics=_Kinematics(), optimizer=_Optimizer(),
    )
    right = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=_Optimizer(),
    )
    for stamp in (1, 2, 3, 4, 5):
        left.process(_frame(stamp, Side.LEFT))
    assert left._filter is not right._filter
    assert left._last_valid is not right._last_valid
    right_result = None
    for stamp in (6, 7, 8, 9, 10):
        right_result = right.process(_frame(stamp))
    assert right_result.command_published is True
    assert left._filter.last_stamp_ns == 5


def test_real_backend_decision_uses_python_bools_for_ros_boolean_arrays():
    session = RetargetingSession(
        Side.RIGHT, _config(), _geometry(), coupling=CouplingModel.from_contract("right"),
        kinematics=_Kinematics(), optimizer=_Optimizer(),
    )
    for stamp in (1, 2, 3, 4, 5):
        decision = session.process(_frame(stamp))

    for values in (
        decision.length_frozen,
        decision.length_current_valid,
        decision.has_valid_ik,
        decision.used_previous_valid_target,
        decision.residual_available,
    ):
        assert all(type(value) is bool for value in values)
    assert all(type(value) is bool for value in decision.target_projection_applied)
    assert all(
        type(value) is bool
        for value in decision.target_projection_distance_available
    )


def test_nlopt_adapter_accepts_objective_only_callback_without_gradient_buffer():
    class _EmptyGradientOptimizer:
        def set_lower_bounds(self, _values):
            pass

        def set_upper_bounds(self, _values):
            pass

        def set_maxeval(self, _value):
            pass

        def set_maxtime(self, _value):
            pass

        def set_min_objective(self, objective):
            self._objective = objective

        def optimize(self, initial):
            self._objective(initial, np.empty(0, dtype=np.float64))
            return initial

        def last_optimize_result(self):
            return 5

    class _EmptyGradientNlopt:
        LD_SLSQP = object()

        @staticmethod
        def opt(_algorithm, _dimension):
            return _EmptyGradientOptimizer()

    from hand_retargeting.adapters.nlopt import NloptSlsqpOptimizer

    optimizer = NloptSlsqpOptimizer(
        CouplingModel.from_contract("right"), _Kinematics(), 10, 0.1
    )
    optimizer._nlopt = _EmptyGradientNlopt
    problem = FingerProblem(
        (0, 1, 2), "R_thumb_tip", 2.0,
        np.array([0.1, 0.2, 0.3]),
        np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]),
    )
    result = optimizer.solve(problem, np.zeros(3))

    assert result.solver_usable is True
    assert result.candidate is not None


def test_nlopt_adapter_discards_candidate_after_unexpected_optimizer_error():
    class _UnexpectedErrorOptimizer:
        def set_lower_bounds(self, _values):
            pass

        def set_upper_bounds(self, _values):
            pass

        def set_maxeval(self, _value):
            pass

        def set_maxtime(self, _value):
            pass

        def set_min_objective(self, objective):
            self._objective = objective

        def optimize(self, initial):
            self._objective(initial, np.empty(0, dtype=np.float64))
            raise RuntimeError("unexpected optimizer failure")

        def last_optimize_result(self):
            return 5

    class _UnexpectedErrorNlopt:
        LD_SLSQP = object()
        ROUNDOFF_LIMITED = -4

        @staticmethod
        def opt(_algorithm, _dimension):
            return _UnexpectedErrorOptimizer()

    from hand_retargeting.adapters.nlopt import NloptSlsqpOptimizer

    optimizer = NloptSlsqpOptimizer(
        CouplingModel.from_contract("right"), _Kinematics(), 10, 0.1
    )
    optimizer._nlopt = _UnexpectedErrorNlopt
    problem = FingerProblem(
        (0, 1, 2), "R_thumb_tip", 2.0,
        np.array([0.1, 0.2, 0.3]),
        np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]),
    )
    result = optimizer.solve(problem, np.zeros(3))

    assert result.candidate is None
    assert result.solver_usable is False
    assert result.result_code == 5


def test_real_backend_adapters_report_blocked_env_without_faking_success():
    from hand_retargeting.adapters.nlopt import NloptSlsqpOptimizer
    from hand_retargeting.adapters.pinocchio import PinocchioFingerKinematics

    try:
        NloptSlsqpOptimizer(None, None, 1, 0.01)
    except NLoptUnavailableError as error:
        assert "BLOCKED_ENV" in str(error)
    else:
        pytest.skip("nlopt is available")
    with pytest.raises(PinocchioUnavailableError, match="BLOCKED_ENV"):
        PinocchioFingerKinematics.from_urdf("missing.urdf", "right")
