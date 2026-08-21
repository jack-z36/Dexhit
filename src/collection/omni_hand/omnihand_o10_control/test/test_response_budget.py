"""Offline response-budget contract for the P3-to-final command path."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
from omnihand_o10_contracts import JOINT_LIMITS, Side


BUDGET_SEC = 0.2
LOW_PASS_95_FACTOR = 3.0
SAMPLE_SEC = 0.001
LIVE_UPDATE_HZ = 30.0
LIVE_SAMPLE_SEC = 1.0 / LIVE_UPDATE_HZ
SOLVER_WORST_CASE_SEC = 0.05
MAX_TIME_CREDIT_SEC = 0.1


def _default_yaml() -> str:
    return Path(__file__).parents[2].joinpath(
        "rokoko_omnihand_bringup", "launchpad", "default.yaml"
    ).read_text(encoding="utf-8")


def _direct_script() -> str:
    return Path(__file__).parents[2].joinpath(
        "rokoko_omnihand_bringup", "scripts", "start_omnihand_control.sh"
    ).read_text(encoding="utf-8")


def _vector(text: str, key: str) -> np.ndarray:
    match = re.search(rf"^\s+{re.escape(key)}:\s*(\[[^\n]+\])\s*$", text, re.MULTILINE)
    assert match, f"default.yaml must define {key}"
    values = ast.literal_eval(match.group(1))
    return np.asarray(values, dtype=np.float64)


def _script_vector(text: str, parameter: str) -> np.ndarray:
    match = re.search(
        rf"-p\s+['\"]?{re.escape(parameter)}:=\[([^\]]+)\]['\"]?",
        text,
    )
    assert match, f"direct launcher must define {parameter}"
    return np.asarray(
        [float(item) for item in match.group(1).split(",")], dtype=np.float64
    )


def _step_settling_time(span: float, rate: float, tau: float) -> float:
    """Simulate a monotonic full-span step and return its 95% time."""
    command = 0.0
    for index in range(1, 1001):
        elapsed = index * SAMPLE_SEC
        soft = span * (1.0 - np.exp(-elapsed / tau))
        command += np.clip(soft - command, -rate * SAMPLE_SEC, rate * SAMPLE_SEC)
        if command >= 0.95 * span:
            return elapsed
    return float("inf")


def _discrete_step_settling_time(amplitude: float, rate: float, tau: float) -> float:
    """Return 95% time for P3 smoothing followed by the final slew limiter."""
    command = 0.0
    for index in range(1, 1001):
        elapsed = index * LIVE_SAMPLE_SEC
        soft = amplitude * (1.0 - np.exp(-elapsed / tau))
        credit = min(LIVE_SAMPLE_SEC, MAX_TIME_CREDIT_SEC)
        command += np.clip(soft - command, -rate * credit, rate * credit)
        if command >= 0.95 * amplitude:
            return elapsed
    return float("inf")


def test_default_full_span_response_budget_includes_p3_smoothing():
    text = _default_yaml()
    taus = _vector(text, "smooth_time_constants")
    assert taus.shape == (10,)
    assert np.all(np.isfinite(taus))
    assert np.all(taus > 0.0)

    for side in (Side.LEFT, Side.RIGHT):
        rates = _vector(text, f"{side.value}.max_joint_rates")
        spans = JOINT_LIMITS[side].upper - JOINT_LIMITS[side].lower
        budget = LOW_PASS_95_FACTOR * taus + spans / rates
        assert np.all(budget <= BUDGET_SEC + 1e-12), (
            f"{side.value} conservative full-span budget exceeds "
            f"{BUDGET_SEC}s: {budget.tolist()}"
        )


def test_default_step_reaches_95_percent_within_budget_for_every_joint():
    text = _default_yaml()
    taus = _vector(text, "smooth_time_constants")
    for side in (Side.LEFT, Side.RIGHT):
        rates = _vector(text, f"{side.value}.max_joint_rates")
        spans = JOINT_LIMITS[side].upper - JOINT_LIMITS[side].lower
        settling = np.asarray(
            [_step_settling_time(span, rate, tau) for span, rate, tau in zip(spans, rates, taus)]
        )
        assert np.all(settling <= BUDGET_SEC), (
            f"{side.value} 95% step settling exceeds {BUDGET_SEC}s: "
            f"{settling.tolist()}"
        )


def test_direct_launcher_matches_default_response_budget():
    yaml_text = _default_yaml()
    script_text = _direct_script()
    taus = _vector(yaml_text, "smooth_time_constants")
    script_taus = _script_vector(script_text, "smooth_time_constants")
    assert np.array_equal(script_taus, taus)

    for side in (Side.LEFT, Side.RIGHT):
        yaml_rates = _vector(yaml_text, f"{side.value}.max_joint_rates")
        script_rates = _script_vector(script_text, f"{side.value}.max_joint_rates")
        assert np.array_equal(script_rates, yaml_rates)
        assert not np.allclose(script_rates, 0.1)


def test_30hz_full_contract_step_includes_solver_worst_case():
    """The production-rate end-to-end software budget must include solver time."""
    text = _default_yaml()
    taus = _vector(text, "smooth_time_constants")
    for side in (Side.LEFT, Side.RIGHT):
        rates = _vector(text, f"{side.value}.max_joint_rates")
        spans = JOINT_LIMITS[side].upper - JOINT_LIMITS[side].lower
        settling = np.asarray(
            [
                _discrete_step_settling_time(span, rate, tau)
                + SOLVER_WORST_CASE_SEC
                for span, rate, tau in zip(spans, rates, taus)
            ]
        )
        assert np.all(settling <= BUDGET_SEC), (
            f"{side.value} 30Hz full-span 95% plus solver budget exceeds "
            f"{BUDGET_SEC}s: {settling.tolist()}"
        )


def test_30hz_typical_live_thumb_and_four_finger_steps_include_solver():
    """Observed-scale thumb and PIP steps must not pass on first-frame motion."""
    text = _default_yaml()
    taus = _vector(text, "smooth_time_constants")
    typical_steps = {
        0: 0.5125,  # thumb_roll range observed in the captured live window
        4: 0.4884,  # index_pip
        5: 0.6312,  # middle_pip
        7: 0.6189,  # ring_pip
        9: 0.5514,  # pinky_pip
    }
    for side in (Side.LEFT, Side.RIGHT):
        rates = _vector(text, f"{side.value}.max_joint_rates")
        settling = {
            index: _discrete_step_settling_time(amplitude, rates[index], taus[index])
            + SOLVER_WORST_CASE_SEC
            for index, amplitude in typical_steps.items()
        }
        assert all(value <= BUDGET_SEC for value in settling.values()), (
            f"{side.value} typical live step budget exceeds {BUDGET_SEC}s: {settling}"
        )
