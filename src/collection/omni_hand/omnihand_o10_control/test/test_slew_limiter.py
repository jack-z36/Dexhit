"""Pure tests for the final hard slew limiter (Spec decision 40; ADR-0003)."""

import math

import numpy as np
import pytest
from omnihand_o10_contracts import JOINT_LIMITS, Side

from omnihand_o10_control.core.slew_limiter import (
    SlewLimiter,
    SlewResultError,
    SlewTimeError,
    SlewUnavailableError,
)

#: A large step only on joint 0 (right thumb_roll has room to 1.12).
BIG_STEP = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_limiter_is_not_initialized_until_a_base_is_adopted():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    assert not limiter.initialized
    with pytest.raises(SlewUnavailableError):
        limiter.limit(BIG_STEP, 1.0, (1e-6,) * 10)


def test_initialize_requires_a_valid_in_limit_vector():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    with pytest.raises(ValueError):
        limiter.initialize([0.0] * 9, 0.0)
    with pytest.raises(ValueError):
        limiter.initialize([math.nan] * 10, 0.0)
    with pytest.raises(ValueError):
        limiter.initialize([1.13] + [0.0] * 9, 0.0)


def test_limit_clips_a_large_step_to_the_maximum_rate():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    command, flags = limiter.limit(BIG_STEP, 1.0, (1e-6,) * 10)
    # rate * min(dt=1.0, max_credit=0.1) = 0.01
    assert np.allclose(command, [0.01] + [0.0] * 9)
    assert flags[0]
    assert not flags[1:].any()


def test_limit_does_not_mutate_the_base():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    limiter.limit(BIG_STEP, 1.0, (1e-6,) * 10)
    assert limiter.base_position == (0.0,) * 10
    assert limiter.base_monotonic == 0.0


def test_limit_passes_through_a_small_step_within_epsilon():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    command, flags = limiter.limit([0.0005] + [0.0] * 9, 0.1, (1e-3,) * 10)
    assert np.allclose(command, [0.0005] + [0.0] * 9)
    assert not flags.any()


def test_confirm_advances_the_base_and_sets_the_clock():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    command, _ = limiter.limit(BIG_STEP, 0.2, (1e-6,) * 10)
    limiter.confirm(command, 0.2)
    assert np.allclose(limiter.base_position, command)
    assert limiter.base_monotonic == 0.2


def test_confirm_rejects_an_out_of_limits_command():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    with pytest.raises(SlewResultError):
        limiter.confirm([1.13] + [0.0] * 9, 0.2)


def test_zero_credit_since_the_clock_origin_produces_a_zero_step():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 1.0)
    command, _ = limiter.limit(BIG_STEP, 1.0 + 1e-9, (1e-6,) * 10)
    assert np.allclose(command, [0.0] * 10)


def test_non_positive_or_non_finite_dt_is_rejected():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 1.0)
    with pytest.raises(SlewTimeError):
        limiter.limit(BIG_STEP, 0.9, (1e-6,) * 10)
    with pytest.raises(SlewTimeError):
        limiter.limit(BIG_STEP, math.inf, (1e-6,) * 10)


def test_rebase_clock_restarts_the_origin_without_changing_the_base():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    limiter.rebase_clock(5.0)
    command, _ = limiter.limit(BIG_STEP, 5.1, (1e-6,) * 10)
    assert np.allclose(command, [0.01] + [0.0] * 9)
    assert limiter.base_position == (0.0,) * 10


def test_clear_time_credit_disables_limiting_until_rebased():
    limiter = SlewLimiter(Side.RIGHT, (0.1,) * 10, 0.1)
    limiter.initialize([0.0] * 10, 0.0)
    limiter.clear_time_credit()
    with pytest.raises(SlewUnavailableError):
        limiter.limit(BIG_STEP, 1.0, (1e-6,) * 10)


@pytest.mark.parametrize("side", [Side.LEFT, Side.RIGHT])
def test_limit_stays_within_the_side_joint_limits(side):
    limits = JOINT_LIMITS[side]
    lower = tuple(float(v) for v in limits.lower)
    upper = tuple(float(v) for v in limits.upper)
    for base in (lower, upper):
        target = upper if base == lower else lower
        limiter = SlewLimiter(side, (0.1,) * 10, 0.1)
        limiter.initialize(base, 0.0)
        command, _ = limiter.limit(target, 1.0, (1e-6,) * 10)
        assert limits.contains(np.asarray(command))


def test_limit_clamps_one_ulp_overshoot_when_a_target_sits_exactly_on_a_limit():
    """Regression: ``base + (limit - base)`` can round one ulp outside the
    limit when a soft target sits exactly on it, which used to raise
    SlewResultError and latch SAFETY_INVARIANT every time the operator drove a
    joint to its limit. The slew output must clamp onto the limit instead."""
    side = Side.LEFT
    limiter = SlewLimiter(side, (1.0,) * 10, 1.0)
    base = [0.0] * 10
    base[1] = 0.39890625
    limiter.initialize(base, 0.0)
    target = [0.0] * 10
    target[1] = float(JOINT_LIMITS[side].lower[1])

    command, _ = limiter.limit(target, 1.0, (1e-9,) * 10)

    assert JOINT_LIMITS[side].contains(np.asarray(command))
    assert command[1] == float(JOINT_LIMITS[side].lower[1])