"""Offline IK failure discriminator tests (T-diag).

The pure tests exercise the decision matrix, start generation, grid
reachability, stationarity and the recording replay seam with fake kinematics.
The real-asset tests at the bottom are opt-in like test_t06_real_assets.py:
they require OMNIHAND_O10_MODEL_FIXTURE plus pinocchio and nlopt.
"""

from __future__ import annotations

import importlib.util
import itertools
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

from hand_retargeting.application.session import FINGER_ACTIVE_INDICES
from hand_retargeting.contracts import RawHandFrameValue, RetargetingConfig
from hand_retargeting.core.coupling import CouplingModel
from hand_retargeting.core.ik import FingerProblem
from hand_retargeting.core.normalization import RobotHandGeometry
import numpy as np
from omnihand_o10_contracts import Side
from omnihand_o10_contracts.joints import JOINT_LIMITS
import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "ik_failure_diagnose.py"
)
_SPEC = importlib.util.spec_from_file_location("ik_failure_diagnose", _SCRIPT_PATH)
diag = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = diag
_SPEC.loader.exec_module(diag)

_REAL_ASSETS_AVAILABLE = (
    bool(__import__("os").environ.get("OMNIHAND_O10_MODEL_FIXTURE"))
    and importlib.util.find_spec("pinocchio") is not None
    and importlib.util.find_spec("nlopt") is not None
)


def _config(**changes):
    values = {
        "palm_y_epsilon": 1e-6,
        "palm_x_epsilon": 1e-6,
        "finger_length_epsilon": 1e-6,
        "length_window_size": 3,
        "stable_window_count": 2,
        "length_nmad_thresholds": (0.01,) * 5,
        "frozen_length_relative_thresholds": (0.10,) * 5,
        "ik_residual_thresholds": (0.05,) * 5,
        "ik_max_evaluations": 10,
        "ik_max_time_sec": 0.01,
        "smooth_time_constants": (0.1,) * 10,
        "stale_timeout_sec": 0.5,
        "recovery_min_valid_frames": 2,
        "recovery_min_duration_sec": 0.1,
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


class _PickKinematics:
    """Deterministic kinematics reading two chosen joints of the full state."""

    def __init__(self, first: int, second: int, z: float = 0.1):
        self.first = first
        self.second = second
        self.z = z

    def tip_position_and_jacobian(self, full_q, tip_frame):
        position = np.array([full_q[self.first], full_q[self.second], self.z])
        jacobian = np.zeros((3, 16))
        jacobian[0, self.first] = 1.0
        jacobian[1, self.second] = 1.0
        return position, jacobian


def _index_full_state_indices():
    """Full-16 state indices of index_abad and index_pip (not the active-10)."""
    from omnihand_o10_model.contract import full_joint_names, joint_name

    full_names = list(full_joint_names("right"))
    return (
        full_names.index(joint_name("right", "index_abad")),
        full_names.index(joint_name("right", "index_pip")),
    )


class _EchoOptimizer:
    """Returns the initial point; enough to drive replay and recording tests."""

    def __init__(self, coupling=None, kinematics=None):
        self.coupling = coupling
        self.kinematics = kinematics

    def solve(self, problem, initial):
        candidate = np.asarray(initial, dtype=float).copy()
        return SimpleNamespace(
            candidate=candidate, result_code=1, evaluations=3,
            elapsed_sec=0.001, solver_usable=True,
        )


def _index_problem(target=(0.0, 0.0, 0.1)):
    limits = JOINT_LIMITS["right"]
    indices = FINGER_ACTIVE_INDICES[1]
    lower = np.asarray([limits.lower[i] for i in indices], dtype=float)
    upper = np.asarray([limits.upper[i] for i in indices], dtype=float)
    return FingerProblem(
        active_indices=indices, tip_frame="R_index_tip", robot_length=2.0,
        target=np.asarray(target, dtype=float), lower=lower, upper=upper,
    )


def _index_grid():
    coupling = CouplingModel.from_contract("right")
    kinematics = _PickKinematics(*_index_full_state_indices())
    return diag.ReachabilityGrid(
        _index_problem(), coupling, kinematics, 41, np.zeros(3),
    )


def test_classify_finger_decision_matrix():
    matrix = [
        # r_single, r_relaxed, r_ms, r_grid, near_singular, expected
        (0.01, 0.01, 0.01, 0.01, False, "not-failing"),
        (0.20, 0.03, 0.20, 0.20, False, "budget-limited"),
        (0.20, 0.20, 0.02, 0.02, False, "B:local-minimum"),
        (0.20, 0.20, 0.19, 0.195, False, "A:unreachable"),
        (0.20, 0.20, 0.20, 0.01, False, "optimizer-insufficient"),
    ]
    for r_single, r_relaxed, r_ms, r_grid, near_singular, expected in matrix:
        verdict = diag.classify_finger(
            r_single=r_single, r_single_relaxed=r_relaxed, r_ms=r_ms,
            r_grid=r_grid, tau=0.05, near_singular=near_singular,
        )["verdict"]
        assert verdict == expected
    with_c = diag.classify_finger(
        r_single=0.2, r_single_relaxed=0.2, r_ms=0.01, r_grid=0.01,
        tau=0.05, near_singular=True,
    )
    assert with_c["verdict"] == "B:local-minimum"
    assert "C" in with_c["detail"]
    solver_error = diag.classify_finger(
        r_single=float("nan"), r_single_relaxed=0.2, r_ms=0.2, r_grid=0.2,
        tau=0.05, near_singular=False,
    )
    assert solver_error["verdict"] != "not-failing"
    unreachable = diag.classify_finger(
        r_single=0.2, r_single_relaxed=0.2, r_ms=0.19, r_grid=0.195,
        tau=0.05, near_singular=False,
    )
    assert unreachable["r_floor"] == pytest.approx(0.19)


def test_classify_unreachable_splits_extension_and_direction():
    grid = _index_grid()
    # The fake kinematics sweeps a rectangle in z=0.1; the grid root is origin.
    assert grid.min_reach == pytest.approx(0.1)
    q_nearest, pos_nearest, _ = grid.nearest(np.asarray((2.5, 0.0, 0.1)))
    over = diag.classify_unreachable(
        np.asarray((2.5, 0.0, 0.1)), grid, q_nearest, pos_nearest
    )
    assert over["subtype"] == "A-ext:over-extension"
    assert over["required_reach"] > over["max_reach"]

    q_under, pos_under, _ = grid.nearest(np.asarray((0.05, 0.05, 0.05)))
    under = diag.classify_unreachable(
        np.asarray((0.05, 0.05, 0.05)), grid, q_under, pos_under
    )
    assert under["subtype"] == "A-under:target-too-close"
    assert under["required_reach"] < under["min_reach"]

    problem = _index_problem()
    half = 0.5 * (problem.lower + problem.upper)
    q_near, pos_near, _ = grid.nearest(np.asarray((half[0], half[1], 0.6)))
    off = diag.classify_unreachable(
        np.asarray((half[0], half[1], 0.6)), grid, q_near, pos_near
    )
    assert off["subtype"] == "A-dir:off-manifold"
    assert off["tangential"] > off["radial"]


def test_generate_starts_covers_deterministic_points_and_respects_bounds():
    problem = _index_problem()
    starts = diag.generate_starts(problem, n_random=16, seed=7)
    points = {tuple(float(v) for v in start) for start in starts}
    midpoint = tuple(float(v) for v in (problem.lower + problem.upper) / 2.0)
    assert midpoint in points
    corners = {
        tuple(float(v) for v in corner)
        for corner in itertools.product(*zip(problem.lower, problem.upper))
    }
    assert corners <= points
    assert len(starts) == len(points)
    repeated = diag.generate_starts(problem, 16, 7)
    assert [list(map(float, start)) for start in repeated[4:]] == [
        list(map(float, start)) for start in starts[4:]
    ]
    for start in starts:
        assert np.all(start >= problem.lower - 1e-12)
        assert np.all(start <= problem.upper + 1e-12)


def test_reachability_grid_matches_fake_identity_kinematics():
    grid = _index_grid()
    problem = _index_problem()
    assert grid.points.shape == (41 * 41, 3)
    inside = 0.5 * (problem.lower + problem.upper)
    q_near, pos_near, distance = grid.nearest(
        np.asarray((inside[0], inside[1], 0.1))
    )
    step = float(np.max(problem.upper - problem.lower)) / 40.0
    assert distance <= 0.71 * step
    assert pos_near[2] == pytest.approx(0.1)
    corners = list(itertools.product(*zip(problem.lower, problem.upper)))
    expected_max = max(
        float(np.linalg.norm(np.asarray([x, y, 0.1]))) for x, y in corners
    )
    assert grid.max_reach == pytest.approx(expected_max)


def test_stationarity_reports_gain_svd_and_bound_projected_gradient():
    coupling = CouplingModel.from_contract("right")
    problem = _index_problem(target=(0.0, 0.0, 0.1))
    kinematics = _PickKinematics(*_index_full_state_indices())
    midpoint = (problem.lower + problem.upper) / 2.0
    report = diag.stationarity(midpoint, problem, coupling, kinematics)
    # G columns are the two unit coordinate axes of the picked joints.
    assert report.sigma_min == pytest.approx(1.0)
    assert report.sigma_max == pytest.approx(1.0)
    assert report.cond == pytest.approx(1.0)
    assert not report.near_singular
    assert report.proj_grad_norm == pytest.approx(report.grad_norm)

    at_bound = problem.lower.copy()
    at_bound[1] = 0.5 * (problem.lower[1] + problem.upper[1])
    bounded = diag.stationarity(at_bound, problem, coupling, kinematics)
    assert list(bounded.at_lower) == [True, False]
    assert list(bounded.at_upper) == [False, False]
    gain = diag.effective_jacobian(at_bound, problem, coupling, kinematics)
    grad = gain.T @ (np.asarray(bounded.position) - problem.target)
    # The bound-active first dimension is excluded from the projected gradient.
    assert bounded.proj_grad_norm == pytest.approx(float(np.linalg.norm(grad[1:])))


def test_recording_optimizer_maps_finger_index_and_records_targets():
    coupling = CouplingModel.from_contract("right")
    kinematics = _PickKinematics(*_index_full_state_indices())
    records = []
    wrapper = diag.RecordingOptimizer(_EchoOptimizer(coupling, kinematics), records)
    wrapper.frame_index = 4
    wrapper.received_at_ns = 123
    problem = _index_problem(target=(0.05, -0.02, 0.3))
    result = wrapper.solve(problem, (problem.lower + problem.upper) / 2.0)
    assert result.candidate is not None
    assert len(records) == 1
    record = records[0]
    assert record.frame_index == 4
    assert record.finger_index == 1
    assert record.received_at_ns == 123
    assert record.target == (0.05, -0.02, 0.3)
    assert record.warm_start is False
    assert math.isfinite(record.residual)
    assert record.result_code == 1
    assert record.evaluations == 3


def test_replay_records_five_finger_problems_and_matches_decision_targets():
    coupling = CouplingModel.from_contract("right")
    kinematics = _PickKinematics(*_index_full_state_indices())
    config = _config(ik_residual_thresholds=(100.0,) * 5)
    frames = [_frame(stamp) for stamp in (1, 2, 3, 4, 5)]
    decisions, records, session = diag.replay_frames(
        frames, config, "right", coupling, kinematics, _geometry(),
        optimizer_factory=lambda: _EchoOptimizer(coupling, kinematics),
    )
    assert all(decision is not None for decision in decisions)
    last = decisions[-1]
    assert last.targets is not None
    frame_records = [r for r in records if r.frame_index == 4]
    assert [r.finger_index for r in frame_records] == [0, 1, 2, 3, 4]
    for record in frame_records:
        assert record.target == tuple(last.targets[record.finger_index])
    assert session._estimators[0].frozen_length is not None


def test_parse_ros_params_extracts_required_keys_and_reports_missing(tmp_path):
    full = {
        "palm_y_epsilon": 1e-6,
        "palm_x_epsilon": 1e-6,
        "finger_length_epsilon": 1e-6,
        "length_window_size": 3,
        "stable_window_count": 2,
        "length_nmad_thresholds": [0.01] * 5,
        "frozen_length_relative_thresholds": [0.10] * 5,
        "ik_residual_thresholds": [0.05] * 5,
        "ik_max_evaluations": 100,
        "ik_max_time_sec": 0.02,
        "smooth_time_constants": [0.1] * 10,
        "stale_timeout_sec": 0.5,
        "recovery_min_valid_frames": 3,
        "recovery_min_duration_sec": 0.1,
    }
    path = tmp_path / (str(uuid.uuid4()) + ".yaml")
    path.write_text(
        "/**:\n  ros__parameters:\n"
        + "".join(f"    {k}: {v!r}\n" for k, v in full.items())
        + "/hand_retargeting:\n  ros__parameters:\n    stale_timeout_sec: 0.7\n",
        encoding="utf-8",
    )
    parsed = diag.parse_ros_params(path)
    assert parsed["stale_timeout_sec"] == 0.7
    assert parsed["ik_max_evaluations"] == 100

    del full["ik_max_evaluations"]
    missing_path = tmp_path / (str(uuid.uuid4()) + ".yaml")
    missing_path.write_text(
        "/**:\n  ros__parameters:\n"
        + "".join(f"    {k}: {v!r}\n" for k, v in full.items()),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ik_max_evaluations"):
        diag.parse_ros_params(missing_path)


def test_build_config_accepts_parsed_yaml_values():
    values = dict(diag.DEFAULT_PARAMS)
    values["ik_max_evaluations"] = 100
    config = diag.build_config(values)
    assert config.ik_residual_thresholds == (0.05,) * 5
    assert config.ik_max_evaluations == 100


def _jsonl_line(kind, **fields):
    import json

    return json.dumps({"type": kind, **fields}) + "\n"


def _raw_line(stamp):
    return _jsonl_line(
        "raw", header_stamp_ns=stamp, node_names=list(_frame(stamp).node_names),
        positions=[list(p) for p in _frame(stamp).positions],
    )


def test_parse_jsonl_segments_frames_by_interleaved_markers(tmp_path):
    path = tmp_path / "session.jsonl"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_jsonl_line("meta", side="left"))
        handle.write(_raw_line(1))
        handle.write(_raw_line(2))
        handle.write(_jsonl_line("marker", label="P0", recorded_ns=10))
        handle.write(_raw_line(3))
        handle.write(_jsonl_line("marker", label="P1", recorded_ns=20))
        handle.write(_raw_line(4))
        handle.write(_jsonl_line("state", header_stamp_ns=4))
    frames, states, meta, frame_poses, markers = diag.parse_jsonl(path)
    assert len(frames) == 4
    assert len(states) == 1
    assert frame_poses == [None, None, "P0", "P1"]
    assert [m["label"] for m in markers] == ["P0", "P1"]
    assert [m["frame_index"] for m in markers] == [2, 3]
    assert meta["side"] == "left"


pytestmark_real = pytest.mark.skipif(
    not _REAL_ASSETS_AVAILABLE,
    reason="real-asset diagnosis checks require OMNIHAND_O10_MODEL_FIXTURE, "
           "pinocchio and nlopt",
)


@pytestmark_real
def test_real_selftest_classifies_synthetic_reachable_and_unreachable():
    assert diag.run_selftest(SimpleNamespace(side="left", seed=20260817)) == 0


@pytestmark_real
def test_real_replay_reproduces_field_like_thumb_failure():
    stack = diag.load_real_stack("right")
    config = _config(
        ik_residual_thresholds=(0.05,) * 5, ik_max_evaluations=250,
        ik_max_time_sec=0.25,
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
        tuple("right" + suffix for suffix in suffixes), tuple(positions), 1
    )
    frames = [
        RawHandFrameValue(frame.node_names, frame.positions, stamp)
        for stamp in range(1, 6)
    ]
    decisions, records, _ = diag.replay_frames(
        frames, config, "right", stack.coupling, stack.kinematics, stack.geometry
    )
    last = decisions[-1]
    assert last.ik_state[0] == "residual-exceeded"
    assert last.has_valid_ik[0] is False
    assert all(last.has_valid_ik[index] for index in range(1, 5))
    assert last.command_published is False
    thumb_records = [r for r in records if r.finger_index == 0]
    assert thumb_records
    assert all(r.residual > 0.05 for r in thumb_records)

    from omnihand_o10_model.contract import tip_link

    record = max(thumb_records, key=lambda r: r.residual)
    problem = FingerProblem(
        active_indices=FINGER_ACTIVE_INDICES[0],
        tip_frame=tip_link("right", "thumb_tip"),
        robot_length=float(stack.geometry.finger_chain_lengths[0]),
        target=np.asarray(record.target, dtype=float),
        lower=np.asarray(record.lower, dtype=float),
        upper=np.asarray(record.upper, dtype=float),
    )
    report = diag.stationarity(
        np.asarray(record.candidate), problem, stack.coupling, stack.kinematics
    )
    assert math.isfinite(report.grad_norm)
    assert report.sigma_min >= 0.0
