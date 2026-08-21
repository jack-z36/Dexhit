#!/usr/bin/env python3
"""Offline discriminator for per-finger IK residual failures.

Reads a JSONL session captured by ``record_retargeting_session.py``, replays the
exact production ``RetargetingSession`` with a recording optimizer wrapper, and
classifies every failing (finger, frame) sample against three competing
hypotheses:

* A  geometric unreachable target (global residual floor above tau),
* B  reachable target but the single production start is trapped in a basin,
* C  the stop point is near-singular (co-factor, measured on G = J_pin @ B).

Two additional non-hypothesis outcomes are separated out: evaluation-budget
limits (T1b) and "grid proves reachable but multi-start missed" (optimizer
insufficiency).  See DOCS/03_工程/06_真机IK残差失败判别报告.md for the decision
matrix once a session has been analysed.

Usage (offline, no ROS runtime needed):

    OMNIHAND_O10_MODEL_FIXTURE=... python3 ik_failure_diagnose.py analyze \
        --jsonl session.jsonl --side left --params production.yaml --out runs/diag

    OMNIHAND_O10_MODEL_FIXTURE=... python3 ik_failure_diagnose.py selftest

This tool is a diagnostic script: it is not installed by setup.py, is not part
of the production launch, and never touches ROS topics or hardware.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import itertools
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Sequence

# --- bootstrap: make sibling ament packages importable when run from source ---
_OMNI_HAND_ROOT = Path(__file__).resolve().parents[2]
for _name in ("hand_retargeting", "omnihand_o10_contracts", "omnihand_o10_model"):
    _candidate = _OMNI_HAND_ROOT / _name
    if _candidate.is_dir():
        sys.path.insert(0, str(_candidate))

from hand_retargeting.adapters.nlopt import NloptSlsqpOptimizer  # noqa: E402
from hand_retargeting.application.session import (  # noqa: E402
    FINGER_ACTIVE_INDICES,
    FINGER_TIP_BASES,
    RetargetingSession,
)
from hand_retargeting.contracts import RawHandFrameValue, RetargetingConfig  # noqa: E402
from hand_retargeting.core.coupling import CouplingModel  # noqa: E402
from hand_retargeting.core.ik import (  # noqa: E402
    FingerProblem,
    objective_and_gradient,
)
import numpy as np  # noqa: E402
from omnihand_o10_contracts import Side  # noqa: E402
from omnihand_o10_contracts.joints import JOINT_LIMITS  # noqa: E402
from omnihand_o10_model.contract import tip_link  # noqa: E402


FINGER_NAMES = ("thumb", "index", "middle", "ring", "little")

# Experimental defaults documented in rokoko_omnihand_system_test graph.py.
# The production YAML should be passed with --params for a faithful replay.
DEFAULT_PARAMS = {
    "palm_y_epsilon": 1e-6,
    "palm_x_epsilon": 1e-6,
    "finger_length_epsilon": 1e-6,
    "length_window_size": 3,
    "stable_window_count": 2,
    "length_nmad_thresholds": (0.01,) * 5,
    "frozen_length_relative_thresholds": (0.10,) * 5,
    "ik_residual_thresholds": (0.05,) * 5,
    "ik_max_evaluations": 100,
    "ik_max_time_sec": 0.02,
    "smooth_time_constants": (0.1,) * 10,
    "stale_timeout_sec": 0.5,
    "recovery_min_valid_frames": 3,
    "recovery_min_duration_sec": 0.1,
    "recovery_confirmation_timeout_sec": 0.5,
}

REQUIRED_PARAM_NAMES = tuple(DEFAULT_PARAMS)


# ---------------------------------------------------------------------------
# Recording replay
# ---------------------------------------------------------------------------


@dataclass
class SolveRecord:
    """One production optimizer invocation captured during offline replay."""

    frame_index: int
    finger_index: int
    received_at_ns: int
    target: tuple[float, float, float]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    initial: tuple[float, ...]
    candidate: tuple[float, ...] | None
    result_code: int
    evaluations: int
    residual: float  # recomputed on the candidate; nan when unavailable
    valid: bool
    warm_start: bool


class RecordingOptimizer:
    """FingerOptimizerPort wrapper that logs every solve for later analysis."""

    def __init__(self, inner, records: list[SolveRecord]):
        self.inner = inner
        self.records = records
        self.frame_index = -1
        self.received_at_ns = 0

    def solve(self, problem: FingerProblem, initial: np.ndarray):
        finger_index = FINGER_ACTIVE_INDICES.index(problem.active_indices)
        result = self.inner.solve(problem, initial)
        residual = float("nan")
        if result.candidate is not None:
            try:
                _, _, residual = objective_and_gradient(
                    result.candidate, problem, self.inner.coupling, self.inner.kinematics
                )
            except (ValueError, FloatingPointError):
                residual = float("nan")
        self.records.append(
            SolveRecord(
                frame_index=self.frame_index,
                finger_index=finger_index,
                received_at_ns=self.received_at_ns,
                target=tuple(float(value) for value in problem.target),
                lower=tuple(float(value) for value in problem.lower),
                upper=tuple(float(value) for value in problem.upper),
                initial=tuple(float(value) for value in initial),
                candidate=(
                    None if result.candidate is None
                    else tuple(float(value) for value in result.candidate)
                ),
                result_code=int(result.result_code),
                evaluations=int(result.evaluations),
                residual=float(residual),
                valid=bool(residual == residual and residual <= 1e9),
                warm_start=not np.allclose(
                    np.asarray(initial, dtype=float),
                    (problem.lower + problem.upper) / 2.0,
                ),
            )
        )
        return result


def replay_frames(
    frames: Sequence[RawHandFrameValue],
    config: RetargetingConfig,
    side: str,
    coupling,
    kinematics,
    robot_geometry,
    optimizer_factory=None,
):
    """Re-run the production session logic over recorded frames.

    Mirrors HandRetargetingNode: stale checks run against the next frame's
    receive stamp, invalid frames are dropped with a warning instead of raising.
    ``optimizer_factory`` overrides the production NLopt construction so pure
    tests can replay without the numeric backend.  Returns (decisions, records,
    session) where decisions[i] corresponds to frames[i] and is None when the
    frame was dropped as invalid.
    """
    if optimizer_factory is None:
        def optimizer_factory():
            return NloptSlsqpOptimizer(
                coupling, kinematics, config.ik_max_evaluations, config.ik_max_time_sec
            )
    records: list[SolveRecord] = []
    wrapper = RecordingOptimizer(optimizer_factory(), records)
    session = RetargetingSession(
        Side.from_value(side), config, robot_geometry,
        coupling=coupling, kinematics=kinematics, optimizer=wrapper,
    )
    decisions = []
    for index, frame in enumerate(frames):
        wrapper.frame_index = index
        wrapper.received_at_ns = frame.received_at_ns
        session.check_stale(frame.received_at_ns)
        try:
            decisions.append(session.process(frame))
        except ValueError as error:
            print(f"[replay] dropped invalid frame {index}: {error}", file=sys.stderr)
            decisions.append(None)
    return decisions, records, session


# ---------------------------------------------------------------------------
# T3: stationarity and conditioning at a stop point
# ---------------------------------------------------------------------------


def effective_jacobian(active, problem: FingerProblem, coupling, kinematics) -> np.ndarray:
    """G = d tip position / d active joints through the passive coupling."""
    active = np.asarray(active, dtype=np.float64)
    full = np.zeros(10, dtype=np.float64)
    full[list(problem.active_indices)] = active
    full_state = coupling.evaluate(full)
    coupling_jacobian = coupling.jacobian(full)[:, list(problem.active_indices)]
    _, full_jacobian = kinematics.tip_position_and_jacobian(full_state, problem.tip_frame)
    return np.asarray(full_jacobian) @ coupling_jacobian


@dataclass
class StationarityReport:
    grad_norm: float
    proj_grad_norm: float
    sigma_min: float
    sigma_max: float
    cond: float
    near_singular: bool
    at_lower: tuple[bool, ...]
    at_upper: tuple[bool, ...]
    error: tuple[float, float, float]
    position: tuple[float, float, float]


def stationarity(active, problem: FingerProblem, coupling, kinematics) -> StationarityReport:
    """Gradient of the squared error, SVD of G and active-bound masks at q."""
    active = np.asarray(active, dtype=np.float64)
    if active.shape != problem.lower.shape or not np.all(np.isfinite(active)):
        raise ValueError("stationarity requires a finite active vector of matching size")
    full = np.zeros(10, dtype=np.float64)
    full[list(problem.active_indices)] = active
    full_state = coupling.evaluate(full)
    position, _ = kinematics.tip_position_and_jacobian(full_state, problem.tip_frame)
    position = np.asarray(position, dtype=np.float64)
    gain = effective_jacobian(active, problem, coupling, kinematics)
    error = position - problem.target
    grad = gain.T @ error
    tol = 1e-9
    free = (active > problem.lower + tol) & (active < problem.upper - tol)
    projected = grad.copy()
    projected[~free] = 0.0
    sigma = np.linalg.svd(gain, compute_uv=False)
    sigma_min = float(sigma.min()) if sigma.size else float("nan")
    sigma_max = float(sigma.max()) if sigma.size else float("nan")
    cond = float(sigma_max / sigma_min) if sigma_min > 0 else float("inf")
    return StationarityReport(
        grad_norm=float(np.linalg.norm(grad)),
        proj_grad_norm=float(np.linalg.norm(projected)),
        sigma_min=sigma_min,
        sigma_max=sigma_max,
        cond=cond,
        near_singular=bool(sigma_min < 1e-3 * sigma_max),
        at_lower=tuple(bool(value) for value in (active <= problem.lower + tol)),
        at_upper=tuple(bool(value) for value in (active >= problem.upper - tol)),
        error=tuple(float(value) for value in error),
        position=tuple(float(value) for value in position),
    )


# ---------------------------------------------------------------------------
# T1: multi-start
# ---------------------------------------------------------------------------


def generate_starts(problem: FingerProblem, n_random: int, seed: int) -> list[np.ndarray]:
    """Deterministic start set: midpoint, corners, clipped zeros, uniform random."""
    starts = [(problem.lower + problem.upper) / 2.0]
    starts.extend(
        np.asarray(corner, dtype=np.float64)
        for corner in itertools.product(*zip(problem.lower, problem.upper))
    )
    clipped_zeros = np.clip(np.zeros_like(problem.lower), problem.lower, problem.upper)
    if not any(np.allclose(clipped_zeros, item) for item in starts):
        starts.append(clipped_zeros)
    if n_random > 0:
        rng = np.random.default_rng(seed)
        starts.extend(
            rng.uniform(problem.lower, problem.upper) for _ in range(n_random)
        )
    return starts


def multi_start(problem: FingerProblem, optimizer, starts: Sequence[np.ndarray]):
    """Best production-budget solve across starts; returns a summary dict."""
    best_residual = float("inf")
    best_start = -1
    best_q = None
    evaluations = 0
    for index, start in enumerate(starts):
        result = optimizer.solve(problem, start)
        evaluations += result.evaluations
        if result.candidate is None:
            continue
        try:
            _, _, residual = objective_and_gradient(
                result.candidate, problem, optimizer.coupling, optimizer.kinematics
            )
        except (ValueError, FloatingPointError):
            continue
        if residual < best_residual:
            best_residual = float(residual)
            best_start = index
            best_q = np.asarray(result.candidate, dtype=np.float64).copy()
    return {
        "r_ms": best_residual,
        "best_start": best_start,
        "n_starts": len(starts),
        "evaluations": evaluations,
        "q_best": None if best_q is None else best_q.tolist(),
    }


# ---------------------------------------------------------------------------
# T2: dense-grid reachability
# ---------------------------------------------------------------------------


class ReachabilityGrid:
    """Sampled reachable tip-point set for one finger (built once, reused)."""

    def __init__(
        self, problem: FingerProblem, coupling, kinematics,
        resolution: int | tuple[int, ...],
        root: np.ndarray,
    ):
        self.problem = problem
        self.coupling = coupling
        self.kinematics = kinematics
        dims = len(problem.active_indices)
        if isinstance(resolution, int):
            resolution = (resolution,) * dims
        self.resolution = tuple(resolution)
        self.root = np.asarray(root, dtype=np.float64)
        self.points: np.ndarray | None = None
        self.q: np.ndarray | None = None
        self._build()

    def _build(self) -> None:
        axes = [
            np.linspace(low, high, res)
            for low, high, res in zip(
                self.problem.lower, self.problem.upper, self.resolution
            )
        ]
        total = int(np.prod([axis.size for axis in axes]))
        self.points = np.empty((total, 3), dtype=np.float64)
        self.q = np.empty((total, len(axes)), dtype=np.float64)
        full = np.zeros(10, dtype=np.float64)
        indices = list(self.problem.active_indices)
        offset = 0
        for combo in itertools.product(*axes):
            full[indices] = combo
            full_state = self.coupling.evaluate(full)
            position, _ = self.kinematics.tip_position_and_jacobian(
                full_state, self.problem.tip_frame
            )
            self.points[offset] = position
            self.q[offset] = combo
            offset += 1

    @property
    def max_reach(self) -> float:
        assert self.points is not None
        return float(np.max(np.linalg.norm(self.points - self.root, axis=1)))

    @property
    def min_reach(self) -> float:
        """Smallest distance from root over the sampled reachable set."""
        assert self.points is not None
        return float(np.min(np.linalg.norm(self.points - self.root, axis=1)))

    def nearest(self, target: np.ndarray):
        """Closest sampled reachable point; returns (q, point, distance)."""
        assert self.points is not None and self.q is not None
        distances = np.linalg.norm(self.points - target, axis=1)
        index = int(np.argmin(distances))
        return self.q[index].copy(), self.points[index].copy(), float(distances[index])

    def residual_of(self, target: np.ndarray) -> float:
        return self.nearest(target)[2] / self.problem.robot_length


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_finger(
    *,
    r_single: float,
    r_single_relaxed: float,
    r_ms: float,
    r_grid: float,
    tau: float,
    near_singular: bool,
) -> dict:
    """Apply the A/B/C decision matrix to one failing sample."""
    if math.isfinite(r_single) and r_single <= tau:
        return {"verdict": "not-failing", "detail": ""}
    if math.isfinite(r_single_relaxed) and r_single_relaxed <= tau:
        return {
            "verdict": "budget-limited",
            "detail": "relaxed-budget midpoint start reaches tau; not A/B/C",
        }
    if math.isfinite(r_ms) and r_ms <= tau:
        return {
            "verdict": "B:local-minimum",
            "detail": (
                "multi-start escapes; stop also near-singular (C co-factor)"
                if near_singular else "multi-start escapes"
            ),
        }
    if math.isfinite(r_grid) and r_grid <= tau:
        return {
            "verdict": "optimizer-insufficient",
            "detail": "grid proves reachable but no multi-start found it",
        }
    floor = min(
        value for value in (r_ms, r_grid) if math.isfinite(value)
    ) if any(math.isfinite(v) for v in (r_ms, r_grid)) else float("nan")
    return {
        "verdict": "A:unreachable",
        "detail": f"global residual floor {floor:.4f} > tau {tau:.4f}",
        "r_floor": float(floor),
    }


def classify_unreachable(target: np.ndarray, grid: ReachabilityGrid, best_q, best_pos):
    """Split an A verdict into over/under-extension vs off-manifold direction.

    Over-extension: the target is farther from the finger root than any
    sampled configuration can reach.  Under-extension: the target sits closer
    to the root than the finger can fold its tip back (inside the reachable
    torus hole).  Everything else is an off-manifold direction: the radius is
    reachable somewhere but not along this direction.
    """
    target = np.asarray(target, dtype=np.float64)
    best_pos = np.asarray(best_pos, dtype=np.float64)
    error = target - best_pos
    radial_vector = best_pos - grid.root
    radial_norm = float(np.linalg.norm(radial_vector))
    if radial_norm > 0.0:
        radial_dir = radial_vector / radial_norm
        radial = float(error @ radial_dir)
        tangential = float(np.linalg.norm(error - radial * radial_dir))
    else:
        radial = 0.0
        tangential = float(np.linalg.norm(error))
    required_reach = float(np.linalg.norm(target - grid.root))
    if required_reach > grid.max_reach + 1e-9:
        subtype = "A-ext:over-extension"
    elif required_reach < grid.min_reach - 1e-9:
        subtype = "A-under:target-too-close"
    else:
        subtype = "A-dir:off-manifold"
    return {
        "subtype": subtype,
        "required_reach": required_reach,
        "max_reach": grid.max_reach,
        "min_reach": grid.min_reach,
        "radial": radial,
        "tangential": tangential,
        "q_nearest": [float(v) for v in best_q],
    }


# ---------------------------------------------------------------------------
# T4: target-side health checks
# ---------------------------------------------------------------------------


def target_side_health(
    session: RetargetingSession,
    records: Sequence[SolveRecord],
    robot_geometry,
    frames: Sequence[RawHandFrameValue],
    side: str,
) -> dict:
    """Aggregate sanity metrics on the generated targets themselves."""
    from hand_retargeting.core.normalization import build_palm_frame

    per_finger = {}
    for finger in range(5):
        finger_records = [r for r in records if r.finger_index == finger]
        root = np.asarray(robot_geometry.finger_roots[finger])
        length = float(robot_geometry.finger_chain_lengths[finger])
        u_norms = [
            float(np.linalg.norm(np.asarray(r.target) - root)) / length
            for r in finger_records
        ]
        frozen = getattr(session._estimators[finger], "frozen_length", None)
        per_finger[FINGER_NAMES[finger]] = {
            "frozen_length": None if frozen is None else float(frozen),
            "u_norm_min": float(np.min(u_norms)) if u_norms else None,
            "u_norm_median": float(np.median(u_norms)) if u_norms else None,
            "u_norm_max": float(np.max(u_norms)) if u_norms else None,
            "robot_chain_length": length,
        }
    thumb_x_sign = None
    if frames:
        try:
            palm = build_palm_frame(frames[-1].positions, Side.from_value(side), session.config)
            thumb_proximal = palm.from_world(frames[-1].positions[1])
            thumb_x_sign = float(np.sign(thumb_proximal[0]))
        except Exception:
            thumb_x_sign = None
    expected_thumb_x_sign = 1.0 if side == "right" else -1.0
    return {
        "fingers": per_finger,
        "thumb_x_sign": thumb_x_sign,
        "expected_thumb_x_sign": expected_thumb_x_sign,
        "thumb_side_consistent": (
            None if thumb_x_sign is None else thumb_x_sign == expected_thumb_x_sign
        ),
    }


# ---------------------------------------------------------------------------
# Inputs: ROS parameter YAML and recorder JSONL
# ---------------------------------------------------------------------------


def parse_ros_params(path: str | Path) -> dict:
    """Extract the retargeting parameter set from a ROS 2 parameters YAML."""
    import yaml

    with open(path, "r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    found: dict = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            params = node.get("ros__parameters")
            if isinstance(params, dict):
                for name in REQUIRED_PARAM_NAMES:
                    if name in params:
                        found[name] = params[name]
            for value in node.values():
                walk(value)

    walk(document)
    missing = [name for name in REQUIRED_PARAM_NAMES if name not in found]
    if missing:
        raise ValueError(
            "parameter YAML is missing required retargeting parameters: "
            + ", ".join(missing)
        )
    return found


def build_config(values: dict) -> RetargetingConfig:
    return RetargetingConfig(
        values["palm_y_epsilon"], values["palm_x_epsilon"], values["finger_length_epsilon"],
        values["length_window_size"], values["stable_window_count"],
        tuple(values["length_nmad_thresholds"]),
        tuple(values["frozen_length_relative_thresholds"]),
        tuple(values["ik_residual_thresholds"]),
        values["ik_max_evaluations"], values["ik_max_time_sec"],
        tuple(values["smooth_time_constants"]),
        values["stale_timeout_sec"], values["recovery_min_valid_frames"],
        values["recovery_min_duration_sec"],
        values["recovery_confirmation_timeout_sec"],
    )


def parse_jsonl(path: str | Path):
    """Load recorder JSONL into (frames, states, meta, frame_poses, markers).

    ``frame_poses[i]`` is the pose label active when frames[i] was recorded,
    resolved from interleaved marker lines in file order.  ``markers`` lists
    every marker event with its position in the frame sequence.
    """
    frames: list[RawHandFrameValue] = []
    states: list[dict] = []
    meta: dict = {}
    frame_poses: list[str | None] = []
    markers: list[dict] = []
    current_pose: str | None = None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            kind = event.get("type")
            if kind == "raw":
                frames.append(
                    RawHandFrameValue(
                        tuple(event["node_names"]),
                        tuple(tuple(point) for point in event["positions"]),
                        int(event["header_stamp_ns"]),
                    )
                )
                frame_poses.append(current_pose)
            elif kind == "state":
                states.append(event)
            elif kind == "meta":
                meta = event
            elif kind == "marker":
                current_pose = str(event.get("label") or current_pose)
                markers.append({
                    "label": current_pose,
                    "frame_index": len(frames),
                    "recorded_ns": event.get("recorded_ns"),
                })
    return frames, states, meta, frame_poses, markers


def replay_fidelity(decisions, states, tolerance: float = 0.02) -> dict:
    """Compare replayed residuals against the live-recorded state residuals."""
    replayed = {
        decision.input_stamp_ns: decision
        for decision in decisions
        if decision is not None
    }
    per_finger = {
        name: {"compared": 0, "matched": 0} for name in FINGER_NAMES
    }
    for state in states:
        stamp = int(state.get("input_stamp_ns", 0))
        decision = replayed.get(stamp)
        if decision is None:
            continue
        for finger in range(5):
            live = state["normalized_residual"][finger]
            local = decision.normalized_residual[finger]
            if not (math.isfinite(live)) and not math.isfinite(local):
                continue
            if not math.isfinite(live) or not math.isfinite(local):
                continue
            entry = per_finger[FINGER_NAMES[finger]]
            entry["compared"] += 1
            if abs(live - local) <= tolerance:
                entry["matched"] += 1
    return per_finger


# ---------------------------------------------------------------------------
# Real asset stack
# ---------------------------------------------------------------------------


@dataclass
class RealStack:
    side: str
    geometry: object
    kinematics: object
    coupling: CouplingModel


def load_real_stack(side: str) -> RealStack:
    """Load geometry, Pinocchio kinematics and coupling from the model fixture."""
    from hand_retargeting.adapters.model_geometry import load_robot_geometry, load_runtime_assets
    from hand_retargeting.adapters.pinocchio import PinocchioFingerKinematics

    if not os.environ.get("OMNIHAND_O10_MODEL_FIXTURE"):
        print(
            "BLOCKED_ENV: set OMNIHAND_O10_MODEL_FIXTURE to the external O10 fixture",
            file=sys.stderr,
        )
        raise SystemExit(2)
    geometry = load_robot_geometry(side)
    assets = load_runtime_assets(side)
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    return RealStack(side=side, geometry=geometry, kinematics=kinematics, coupling=coupling)


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------


@dataclass
class AnalysisOptions:
    n_random_starts: int = 64
    seed: int = 20260817
    max_samples_per_finger: int = 20
    grid_resolution_1d: int = 2001
    grid_resolution_2d: int = 601
    grid_resolution_3d: int = 61
    polish_evaluations: int = 500
    polish_time_sec: float = 2.0
    out_dir: Path = field(default_factory=lambda: Path("runs/ik_diagnosis"))


def _select_samples(records, taus: Sequence[float], max_samples: int):
    """Failing records per finger, evenly spaced, worst frame always included."""
    selected: dict[int, list[SolveRecord]] = {}
    for finger in range(5):
        failing = [
            record for record in records
            if record.finger_index == finger
            and (not math.isfinite(record.residual) or record.residual > taus[finger])
        ]
        if not failing:
            continue
        if len(failing) <= max_samples:
            chosen = failing
        else:
            positions = np.linspace(0, len(failing) - 1, max_samples - 1, dtype=int)
            chosen = [failing[int(p)] for p in positions]
            worst = max(failing, key=lambda r: (r.residual if math.isfinite(r.residual) else -1))
            if worst not in chosen:
                chosen.append(worst)
        selected[finger] = chosen
    return selected


def analyze_sample(
    record: SolveRecord,
    tau: float,
    config: RetargetingConfig,
    stack: RealStack,
    grid: ReachabilityGrid,
    options: AnalysisOptions,
) -> dict:
    """Run T1b, T1, T2 and T3 for one failing (finger, frame) sample."""
    problem = FingerProblem(
        active_indices=FINGER_ACTIVE_INDICES[record.finger_index],
        tip_frame=tip_link(stack.side, FINGER_TIP_BASES[record.finger_index]),
        robot_length=float(stack.geometry.finger_chain_lengths[record.finger_index]),
        target=np.asarray(record.target, dtype=np.float64),
        lower=np.asarray(record.lower, dtype=np.float64),
        upper=np.asarray(record.upper, dtype=np.float64),
    )
    midpoint = (problem.lower + problem.upper) / 2.0

    relaxed_optimizer = NloptSlsqpOptimizer(
        stack.coupling, stack.kinematics,
        config.ik_max_evaluations * 10, config.ik_max_time_sec * 10.0,
    )
    relaxed = relaxed_optimizer.solve(problem, midpoint)
    r_single_relaxed = float("nan")
    if relaxed.candidate is not None:
        try:
            _, _, r_single_relaxed = objective_and_gradient(
                relaxed.candidate, problem, stack.coupling, stack.kinematics
            )
        except (ValueError, FloatingPointError):
            r_single_relaxed = float("nan")

    production_optimizer = NloptSlsqpOptimizer(
        stack.coupling, stack.kinematics,
        config.ik_max_evaluations, config.ik_max_time_sec,
    )
    starts = generate_starts(problem, options.n_random_starts, options.seed)
    multi = multi_start(problem, production_optimizer, starts)

    q_nearest, pos_nearest, _ = grid.nearest(problem.target)
    r_grid = float(np.linalg.norm(pos_nearest - problem.target) / problem.robot_length)
    polish_optimizer = NloptSlsqpOptimizer(
        stack.coupling, stack.kinematics,
        options.polish_evaluations, options.polish_time_sec,
    )
    polished = polish_optimizer.solve(problem, q_nearest)
    r_grid_polished = r_grid
    best_q, best_pos = q_nearest, pos_nearest
    if polished.candidate is not None:
        try:
            _, _, r_polished = objective_and_gradient(
                polished.candidate, problem, stack.coupling, stack.kinematics
            )
            if math.isfinite(r_polished) and r_polished < r_grid:
                r_grid_polished = float(r_polished)
                full = np.zeros(10)
                full[list(problem.active_indices)] = polished.candidate
                best_pos = np.asarray(
                    stack.kinematics.tip_position_and_jacobian(
                        stack.coupling.evaluate(full), problem.tip_frame
                    )[0]
                )
                best_q = np.asarray(polished.candidate, dtype=np.float64)
        except (ValueError, FloatingPointError):
            pass

    stop: dict | None = None
    near_singular = False
    if record.candidate is not None:
        try:
            report = stationarity(
                np.asarray(record.candidate), problem, stack.coupling, stack.kinematics
            )
            near_singular = report.near_singular
            stop = {
                "grad_norm": report.grad_norm,
                "proj_grad_norm": report.proj_grad_norm,
                "sigma_min": report.sigma_min,
                "sigma_max": report.sigma_max,
                "cond": report.cond,
                "at_lower": list(report.at_lower),
                "at_upper": list(report.at_upper),
            }
        except ValueError:
            stop = None

    classification = classify_finger(
        r_single=record.residual,
        r_single_relaxed=r_single_relaxed,
        r_ms=multi["r_ms"],
        r_grid=min(r_grid, r_grid_polished),
        tau=tau,
        near_singular=near_singular,
    )
    result = {
        "frame_index": record.frame_index,
        "received_at_ns": record.received_at_ns,
        "finger": FINGER_NAMES[record.finger_index],
        "target": [float(value) for value in problem.target],
        "r_single": record.residual,
        "r_single_relaxed": r_single_relaxed,
        "r_ms": multi["r_ms"],
        "best_start": multi["best_start"],
        "r_grid": r_grid,
        "r_grid_polished": r_grid_polished,
        "stop": stop,
        "verdict": classification["verdict"],
        "detail": classification["detail"],
    }
    if classification["verdict"] == "A:unreachable":
        result["unreachable"] = classify_unreachable(
            problem.target, grid, best_q, best_pos
        )
    return result


def run_analyze(arguments) -> int:
    frames, states, meta, frame_poses, markers = parse_jsonl(arguments.jsonl)
    if not frames:
        print(f"no raw frames found in {arguments.jsonl}", file=sys.stderr)
        return 2
    side = arguments.side
    params = dict(DEFAULT_PARAMS)
    if arguments.params:
        params.update(parse_ros_params(arguments.params))
        print(f"using parameters from {arguments.params}")
    else:
        print(
            "WARNING: no --params given; replaying with documented experimental "
            "defaults which may differ from production (see graph.py)"
        )
    config = build_config(params)
    stack = load_real_stack(side)
    print(
        f"replaying {len(frames)} frames on side {side} "
        f"(ik budget {config.ik_max_evaluations} evals / {config.ik_max_time_sec}s)"
    )
    decisions, records, session = replay_frames(
        frames, config, side, stack.coupling, stack.kinematics, stack.geometry
    )
    fidelity = replay_fidelity(decisions, states)
    health = target_side_health(session, records, stack.geometry, frames, side)

    options = AnalysisOptions(
        n_random_starts=arguments.multistart,
        max_samples_per_finger=arguments.max_samples,
        out_dir=Path(arguments.out),
    )
    per_finger_tau = {
        finger: config.ik_residual_thresholds[finger] for finger in range(5)
    }
    selected = _select_samples(
        records, [per_finger_tau[f] for f in range(5)], options.max_samples_per_finger
    )

    results: list[dict] = []
    grids: dict[int, ReachabilityGrid] = {}
    for finger in sorted(selected):
        dims = len(FINGER_ACTIVE_INDICES[finger])
        resolution = {
            1: options.grid_resolution_1d,
            2: options.grid_resolution_2d,
            3: options.grid_resolution_3d,
        }[dims]
        template = selected[finger][0]
        grid = ReachabilityGrid(
            FingerProblem(
                active_indices=FINGER_ACTIVE_INDICES[finger],
                tip_frame=tip_link(side, FINGER_TIP_BASES[finger]),
                robot_length=float(stack.geometry.finger_chain_lengths[finger]),
                target=np.asarray(template.target, dtype=np.float64),
                lower=np.asarray(template.lower, dtype=np.float64),
                upper=np.asarray(template.upper, dtype=np.float64),
            ),
            stack.coupling, stack.kinematics, resolution,
            np.asarray(stack.geometry.finger_roots[finger]),
        )
        grids[finger] = grid
        print(
            f"finger {FINGER_NAMES[finger]}: grid {grid.points.shape[0]} points, "
            f"max reach {grid.max_reach:.4f} m, {len(selected[finger])} failing samples"
        )
        for record in selected[finger]:
            started = time.perf_counter()
            sample = analyze_sample(
                record, per_finger_tau[finger], config, stack, grid, options
            )
            sample["pose"] = frame_poses[record.frame_index]
            sample["analysis_sec"] = round(time.perf_counter() - started, 3)
            results.append(sample)
            print(
                f"  frame {sample['frame_index']}: r_single={sample['r_single']:.3f} "
                f"r_ms={sample['r_ms']:.3f} r_grid={sample['r_grid_polished']:.3f} "
                f"-> {sample['verdict']}"
            )

    options.out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "jsonl": str(arguments.jsonl),
            "recorder_meta": meta,
            "markers": markers,
            "side": side,
            "params": {k: list(v) if isinstance(v, tuple) else v for k, v in params.items()},
            "n_frames": len(frames),
            "options": {
                "n_random_starts": options.n_random_starts,
                "grid_2d": options.grid_resolution_2d,
                "grid_3d": options.grid_resolution_3d,
            },
        },
        "fidelity": fidelity,
        "target_health": health,
        "results": results,
    }
    json_path = options.out_dir / "diagnosis.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    markdown_path = _write_markdown(payload, options.out_dir / "diagnosis.md")
    print(f"wrote {json_path} and {markdown_path}")
    if arguments.plots:
        _write_plots(payload, grids, stack, options.out_dir)
    return 0


def _write_markdown(payload: dict, path: Path) -> Path:
    lines = ["# IK failure diagnosis", ""]
    meta = payload["meta"]
    lines.append(f"- side: `{meta['side']}`, frames: {meta['n_frames']}")
    lines.append(f"- jsonl: `{meta['jsonl']}`")
    lines.append(
        "- ik budget: {} evals / {} s, thresholds: {}".format(
            meta["params"]["ik_max_evaluations"],
            meta["params"]["ik_max_time_sec"],
            meta["params"]["ik_residual_thresholds"],
        )
    )
    lines.append("")
    lines.append("## Replay fidelity (offline replay vs live state residuals)")
    lines.append("")
    lines.append("| finger | compared | matched (|dr|<=0.02) |")
    lines.append("| --- | --- | --- |")
    for name, entry in payload["fidelity"].items():
        lines.append(f"| {name} | {entry['compared']} | {entry['matched']} |")
    lines.append("")
    lines.append("## Target-side health (T4)")
    lines.append("")
    lines.append("| finger | frozen length (m) | robot chain (m) | ‖u‖ min/med/max |")
    lines.append("| --- | --- | --- | --- |")
    for name, entry in payload["target_health"]["fingers"].items():
        frozen = entry["frozen_length"]
        frozen_text = "-" if frozen is None else f"{frozen:.4f}"
        stats = entry["u_norm_min"]
        if stats is None:
            u_text = "-"
        else:
            u_text = (
                f"{entry['u_norm_min']:.3f}/{entry['u_norm_median']:.3f}/"
                f"{entry['u_norm_max']:.3f}"
            )
        lines.append(
            f"| {name} | {frozen_text} | {entry['robot_chain_length']:.4f} | {u_text} |"
        )
    thumb = payload["target_health"]
    lines.append("")
    lines.append(
        f"- thumb proximal X sign in palm frame: {thumb['thumb_x_sign']} "
        f"(expected {thumb['expected_thumb_x_sign']}, "
        f"consistent: {thumb['thumb_side_consistent']})"
    )
    lines.append("")
    lines.append("## Pose segments")
    lines.append("")
    if meta.get("markers"):
        lines.append("| label | from frame |")
        lines.append("| --- | --- |")
        for marker in meta["markers"]:
            lines.append(f"| {marker['label']} | {marker['frame_index']} |")
    else:
        lines.append("no pose markers recorded (frames carry pose `None`)")
    lines.append("")
    lines.append("## Per-sample verdicts")
    lines.append("")
    lines.append(
        "| pose | finger | frame | r_single | r_relaxed | r_ms | r_grid | "
        "σmin(G) | cond | verdict |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for sample in payload["results"]:
        stop = sample.get("stop")
        sigma = "-" if stop is None else f"{stop['sigma_min']:.2e}"
        cond = "-" if stop is None else f"{stop['cond']:.1f}"
        unreachable = sample.get("unreachable")
        verdict = sample["verdict"]
        if unreachable is not None:
            verdict += f" ({unreachable['subtype']})"
        lines.append(
            "| {} | {} | {} | {:.3f} | {} | {:.3f} | {:.3f} | {} | {} | {} |".format(
                sample.get("pose") or "-",
                sample["finger"], sample["frame_index"], sample["r_single"],
                "-" if not math.isfinite(sample["r_single_relaxed"])
                else f"{sample['r_single_relaxed']:.3f}",
                sample["r_ms"], sample["r_grid_polished"], sigma, cond, verdict,
            )
        )
    lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def _write_plots(payload, grids, stack: RealStack, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as error:
        print(f"plots skipped (matplotlib unavailable: {error})", file=sys.stderr)
        return
    for finger, grid in grids.items():
        targets = np.asarray(
            [
                result["target"] for result in payload["results"]
                if result["finger"] == FINGER_NAMES[finger]
            ]
        )
        # targets are not stored per-result; reconstruct from grid samples is not
        # possible, so plots use reachable set plus roots only.
        fig = plt.figure(figsize=(8, 7))
        axis = fig.add_subplot(111, projection="3d")
        step = max(1, grid.points.shape[0] // 15000)
        axis.scatter(
            grid.points[::step, 0], grid.points[::step, 1], grid.points[::step, 2],
            s=1, alpha=0.25, label="reachable set",
        )
        axis.scatter(*grid.root, color="red", s=40, label="finger root")
        if targets is not None and len(targets):
            axis.scatter(targets[:, 0], targets[:, 1], targets[:, 2],
                         color="orange", s=12, label="failed targets")
        axis.set_title(FINGER_NAMES[finger])
        axis.legend()
        fig.savefig(out_dir / f"reachability_{FINGER_NAMES[finger]}.png", dpi=120)
        plt.close(fig)
    print(f"plots written to {out_dir}")


# ---------------------------------------------------------------------------
# Selftest (offline smoke on synthetic reachable / unreachable targets)
# ---------------------------------------------------------------------------


def run_selftest(arguments) -> int:
    side = arguments.side
    stack = load_real_stack(side)
    failures = []
    for finger in (0, 3):
        active_indices = FINGER_ACTIVE_INDICES[finger]
        limits = JOINT_LIMITS[side]
        lower = np.asarray([limits.lower[i] for i in active_indices], dtype=float)
        upper = np.asarray([limits.upper[i] for i in active_indices], dtype=float)
        frame = tip_link(side, FINGER_TIP_BASES[finger])
        length = float(stack.geometry.finger_chain_lengths[finger])
        dims = len(active_indices)
        resolution = {1: 2001, 2: 301, 3: 31}[dims]

        def problem_for(target):
            return FingerProblem(
                active_indices=active_indices, tip_frame=frame,
                robot_length=length, target=target, lower=lower, upper=upper,
            )

        seed_q = lower + 0.3 * (upper - lower)
        full = np.zeros(10)
        full[list(active_indices)] = seed_q
        reachable_target = np.asarray(
            stack.kinematics.tip_position_and_jacobian(
                stack.coupling.evaluate(full), frame
            )[0]
        )
        root = np.asarray(stack.geometry.finger_roots[finger])
        far_target = root + 3.0 * length * np.asarray((0.0, 0.0, 1.0))

        grid = ReachabilityGrid(
            problem_for(reachable_target), stack.coupling, stack.kinematics,
            resolution, root,
        )
        tau = 0.05
        optimizer = NloptSlsqpOptimizer(stack.coupling, stack.kinematics, 250, 0.25)
        for label, target, expect_a in (
            ("reachable", reachable_target, False),
            ("far", far_target, True),
        ):
            problem = problem_for(target)
            single = optimizer.solve(problem, (lower + upper) / 2.0)
            r_single = float("nan")
            if single.candidate is not None:
                _, _, r_single = objective_and_gradient(
                    single.candidate, problem, stack.coupling, stack.kinematics
                )
            multi = multi_start(
                problem, optimizer,
                generate_starts(problem, 16, arguments.seed),
            )
            r_grid = grid.residual_of(target)
            verdict = classify_finger(
                r_single=r_single, r_single_relaxed=float("nan"),
                r_ms=multi["r_ms"], r_grid=r_grid, tau=tau, near_singular=False,
            )["verdict"]
            print(
                f"[selftest] {side}/{FINGER_NAMES[finger]}/{label}: "
                f"r_single={r_single:.4f} r_ms={multi['r_ms']:.4f} "
                f"r_grid={r_grid:.4f} -> {verdict}"
            )
            if expect_a and verdict != "A:unreachable":
                failures.append(f"{FINGER_NAMES[finger]}/{label}: expected A, got {verdict}")
            if not expect_a and verdict == "A:unreachable":
                failures.append(f"{FINGER_NAMES[finger]}/{label}: unexpected A verdict")
    if failures:
        print("SELFTEST FAILED:", *failures, sep="\n  ", file=sys.stderr)
        return 1
    print("selftest passed")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze", help="classify failing samples from a recorded JSONL session"
    )
    analyze_parser.add_argument("--jsonl", required=True)
    analyze_parser.add_argument("--side", default="left", choices=("left", "right"))
    analyze_parser.add_argument("--params", default=None, help="ROS parameter YAML")
    analyze_parser.add_argument("--out", default="runs/ik_diagnosis")
    analyze_parser.add_argument("--multistart", type=int, default=64)
    analyze_parser.add_argument("--max-samples", type=int, default=20)
    analyze_parser.add_argument("--seed", type=int, default=20260817)
    analyze_parser.add_argument("--plots", action="store_true")
    analyze_parser.set_defaults(handler=run_analyze)

    selftest_parser = subparsers.add_parser("selftest", help="synthetic smoke check")
    selftest_parser.add_argument("--side", default="left", choices=("left", "right"))
    selftest_parser.add_argument("--seed", type=int, default=20260817)
    selftest_parser.set_defaults(handler=run_selftest)

    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
