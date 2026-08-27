"""Tests for the pure joint value objects (acceptance: target/feedback/error/time).

Each position-domain value object (target, feedback) validates 10-dim, finite and
within the per-side limits; rejection is explicit (typed error), never silent.
JointError validates 10-dim and finite (vendor error bits are not position-domain,
so they are intentionally not checked against rad joint limits).
"""

import math

import numpy as np
import pytest

from omnihand_o10_contracts import (
    JOINT_LIMITS,
    JointError,
    JointFeedback,
    JointSampleTime,
    JointTarget,
    Side,
)
from omnihand_o10_contracts.errors import (
    InvalidJointVectorError,
    InvalidSampleTimeError,
)


def _midpoint(side: Side) -> np.ndarray:
    lo = JOINT_LIMITS[side].lower
    hi = JOINT_LIMITS[side].upper
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# JointSampleTime
# ---------------------------------------------------------------------------


class TestJointSampleTime:
    @pytest.mark.parametrize("seconds", [0.0, 1.5, 123456789.0])
    def test_accepts_finite_non_negative(self, seconds):
        stamp = JointSampleTime(seconds)
        assert stamp.seconds == seconds

    @pytest.mark.parametrize("bad", [-1e-9, -100.0])
    def test_rejects_negative(self, bad):
        with pytest.raises(InvalidSampleTimeError):
            JointSampleTime(bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_non_finite(self, bad):
        with pytest.raises(InvalidSampleTimeError):
            JointSampleTime(bad)

    def test_is_immutable(self):
        stamp = JointSampleTime(1.0)
        with pytest.raises(Exception):
            stamp.seconds = 2.0  # type: ignore[misc]

    def test_value_equality(self):
        assert JointSampleTime(1.0) == JointSampleTime(1.0)
        assert JointSampleTime(1.0) != JointSampleTime(2.0)


# ---------------------------------------------------------------------------
# Shared position-domain behaviour (target + feedback share validation rules)
# ---------------------------------------------------------------------------


@pytest.fixture(params=[JointTarget, JointFeedback])
def position_value_cls(request):
    return request.param


class TestPositionValueObjectsValid:
    def test_accepts_a_valid_ten_vector_at_midpoint(self, position_value_cls):
        for side in Side:
            value = position_value_cls(side=side, values=_midpoint(side),
                                       stamp=1.0)
            assert value.side is side
            assert value.values.shape == (10,)
            np.testing.assert_allclose(value.values, _midpoint(side))

    def test_accepts_list_tuple_or_ndarray_input(self, position_value_cls):
        side = Side.RIGHT
        for values in (list(_midpoint(side)),
                       tuple(_midpoint(side)),
                       _midpoint(side)):
            value = position_value_cls(side=side, values=values, stamp=0.0)
            np.testing.assert_allclose(value.values, _midpoint(side))

    def test_accepts_exact_lower_and_upper_bounds(self, position_value_cls):
        # Boundary inclusivity: a value exactly on a limit is valid.
        for side in Side:
            limits = JOINT_LIMITS[side]
            value_lo = position_value_cls(side=side, values=limits.lower,
                                          stamp=0.0)
            value_hi = position_value_cls(side=side, values=limits.upper,
                                          stamp=0.0)
            np.testing.assert_allclose(value_lo.values, limits.lower)
            np.testing.assert_allclose(value_hi.values, limits.upper)

    def test_stamp_normalises_float_and_sample_time(self, position_value_cls):
        side = Side.RIGHT
        v_float = position_value_cls(side=side, values=_midpoint(side), stamp=2.5)
        v_stamp = position_value_cls(side=side, values=_midpoint(side),
                                     stamp=JointSampleTime(2.5))
        assert isinstance(v_float.stamp, JointSampleTime)
        assert v_float.stamp.seconds == 2.5
        assert v_stamp.stamp.seconds == 2.5
        assert v_float.stamp_seconds == 2.5


class TestPositionValueObjectsReject:
    @pytest.mark.parametrize("length", [0, 1, 9, 11, 16])
    def test_rejects_wrong_dimension(self, position_value_cls, length):
        with pytest.raises(InvalidJointVectorError):
            position_value_cls(side=Side.RIGHT, values=[0.0] * length, stamp=0.0)

    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"),
                                           float("-inf")])
    def test_rejects_non_finite_components(self, position_value_cls, bad_value):
        side = Side.RIGHT
        values = list(_midpoint(side))
        values[3] = bad_value
        with pytest.raises(InvalidJointVectorError):
            position_value_cls(side=side, values=values, stamp=0.0)

    def test_rejects_value_above_upper_limit(self, position_value_cls):
        side = Side.RIGHT
        values = list(_midpoint(side))
        # index_pip (index 4) upper limit is 1.48
        values[4] = 1.48 + 0.01
        with pytest.raises(InvalidJointVectorError):
            position_value_cls(side=side, values=values, stamp=0.0)

    def test_rejects_value_below_lower_limit(self, position_value_cls):
        side = Side.RIGHT
        values = list(_midpoint(side))
        # thumb_abad (index 1) lower limit is -1.64
        values[1] = -1.64 - 0.01
        with pytest.raises(InvalidJointVectorError):
            position_value_cls(side=side, values=values, stamp=0.0)

    def test_rejection_error_is_typed_and_carries_context(self,
                                                          position_value_cls):
        side = Side.RIGHT
        values = list(_midpoint(side))
        values[4] = 999.0
        with pytest.raises(InvalidJointVectorError) as exc_info:
            position_value_cls(side=side, values=values, stamp=0.0)
        assert exc_info.value.side is side

    def test_rejects_negative_stamp(self, position_value_cls):
        with pytest.raises(InvalidSampleTimeError):
            position_value_cls(side=Side.RIGHT, values=_midpoint(Side.RIGHT),
                               stamp=-0.1)

    def test_rejects_non_finite_stamp(self, position_value_cls):
        with pytest.raises(InvalidSampleTimeError):
            position_value_cls(side=Side.RIGHT, values=_midpoint(Side.RIGHT),
                               stamp=float("nan"))


class TestPerSideLimitEnforcement:
    """A value valid for one side may be invalid for the other (decision 24)."""

    def _vector_with_thumb_roll(self, roll: float) -> list[float]:
        vec = [0.0] * 10
        vec[0] = roll
        # zero is within limits for all other joints on both sides.
        return vec

    def test_thumb_roll_valid_for_right_invalid_for_left(self, position_value_cls):
        # right thumb_roll in [-0.03, 1.12]; left thumb_roll in [-1.12, 0.03].
        vec = self._vector_with_thumb_roll(1.0)
        # valid on the right (1.0 <= 1.12)
        position_value_cls(side=Side.RIGHT, values=vec, stamp=0.0)
        # rejected on the left (1.0 > 0.03)
        with pytest.raises(InvalidJointVectorError):
            position_value_cls(side=Side.LEFT, values=vec, stamp=0.0)

    def test_thumb_roll_negative_valid_for_left_invalid_for_right(
            self, position_value_cls):
        # -1.0 is valid on the left (-1.0 >= -1.12) but invalid on the right.
        vec = self._vector_with_thumb_roll(-1.0)
        position_value_cls(side=Side.LEFT, values=vec, stamp=0.0)
        with pytest.raises(InvalidJointVectorError):
            position_value_cls(side=Side.RIGHT, values=vec, stamp=0.0)


class TestValueObjectSemantics:
    def test_target_and_feedback_are_distinct_types(self):
        assert JointTarget is not JointFeedback

    def test_value_arrays_are_immutable(self, position_value_cls):
        value = position_value_cls(side=Side.RIGHT,
                                   values=_midpoint(Side.RIGHT), stamp=0.0)
        assert not value.values.flags.writeable
        with pytest.raises(ValueError):
            value.values[0] = 99.0

    def test_value_object_is_immutable(self, position_value_cls):
        value = position_value_cls(side=Side.RIGHT,
                                   values=_midpoint(Side.RIGHT), stamp=0.0)
        with pytest.raises(Exception):
            value.side = Side.LEFT  # type: ignore[misc]
        with pytest.raises(Exception):
            value.stamp = 5.0  # type: ignore[misc]

    def test_value_equality_is_by_content(self, position_value_cls):
        side = Side.RIGHT
        a = position_value_cls(side=side, values=_midpoint(side), stamp=1.0)
        b = position_value_cls(side=side, values=_midpoint(side), stamp=1.0)
        c = position_value_cls(side=side, values=_midpoint(side), stamp=2.0)
        assert a == b
        assert a != c

    def test_value_object_hashable(self, position_value_cls):
        side = Side.RIGHT
        a = position_value_cls(side=side, values=_midpoint(side), stamp=1.0)
        b = position_value_cls(side=side, values=_midpoint(side), stamp=1.0)
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_input_array_is_defensively_copied(self, position_value_cls):
        side = Side.RIGHT
        src = list(_midpoint(side))
        value = position_value_cls(side=side, values=src, stamp=0.0)
        # mutating the caller's copy must not affect the immutable value object
        src[0] = -999.0
        np.testing.assert_allclose(value.values, _midpoint(side))


# ---------------------------------------------------------------------------
# JointError (vendor 10-joint error state)
# ---------------------------------------------------------------------------


class TestJointError:
    def test_accepts_ten_finite_components(self):
        for side in Side:
            err = JointError(side=side, values=[0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                             stamp=0.0)
            assert err.side is side
            assert err.values.shape == (10,)

    @pytest.mark.parametrize("length", [9, 11])
    def test_rejects_wrong_dimension(self, length):
        with pytest.raises(InvalidJointVectorError):
            JointError(side=Side.RIGHT, values=[0] * length, stamp=0.0)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_rejects_non_finite(self, bad):
        values = [0.0] * 10
        values[5] = bad
        with pytest.raises(InvalidJointVectorError):
            JointError(side=Side.RIGHT, values=values, stamp=0.0)

    def test_error_state_outside_rad_limits_is_accepted(self):
        # Error bits are not position-domain rad values, so they are NOT checked
        # against joint limits; only dimension and finiteness are enforced.
        JointError(side=Side.RIGHT, values=[1000.0] * 10, stamp=0.0)

    def test_rejects_negative_stamp(self):
        with pytest.raises(InvalidSampleTimeError):
            JointError(side=Side.RIGHT, values=[0] * 10, stamp=-1.0)

    def test_values_are_immutable(self):
        err = JointError(side=Side.RIGHT, values=[0] * 10, stamp=0.0)
        assert not err.values.flags.writeable
        with pytest.raises(ValueError):
            err.values[0] = 1.0
