"""Tests for the single O10 active-joint contract: names, indices, limits (A11).

The fixed active-joint order is Spec decision 24:
thumb_roll, thumb_abad, thumb_mcp, index_abad, index_pip, middle_pip,
ring_abad, ring_pip, pinky_abad, pinky_pip.

omnihand_o10_contracts is the ONLY code owner of these facts (invariant A11).
"""

import numpy as np
import pytest

from omnihand_o10_contracts import (
    ACTIVE_JOINT_COUNT,
    ACTIVE_JOINT_INDEX,
    ACTIVE_JOINT_NAMES,
    JOINT_LIMITS,
    JointLimits,
    Side,
)


EXPECTED_NAMES = (
    "thumb_roll",
    "thumb_abad",
    "thumb_mcp",
    "index_abad",
    "index_pip",
    "middle_pip",
    "ring_abad",
    "ring_pip",
    "pinky_abad",
    "pinky_pip",
)


class TestActiveJointNames:
    def test_count_is_exactly_ten(self):
        assert ACTIVE_JOINT_COUNT == 10
        assert len(ACTIVE_JOINT_NAMES) == 10

    def test_names_match_spec_decision_24_in_fixed_order(self):
        assert tuple(ACTIVE_JOINT_NAMES) == EXPECTED_NAMES

    def test_names_are_unique(self):
        assert len(set(ACTIVE_JOINT_NAMES)) == len(ACTIVE_JOINT_NAMES)

    def test_names_are_immutable(self):
        with pytest.raises(TypeError):
            ACTIVE_JOINT_NAMES[0] = "sabotage"  # type: ignore[index]


class TestActiveJointIndex:
    def test_index_maps_each_name_to_its_fixed_position(self):
        for position, name in enumerate(EXPECTED_NAMES):
            assert ACTIVE_JOINT_INDEX[name] == position

    def test_index_size_matches_names(self):
        assert len(ACTIVE_JOINT_INDEX) == len(ACTIVE_JOINT_NAMES)

    def test_unknown_name_is_not_in_index(self):
        assert "wrist_pitch" not in ACTIVE_JOINT_INDEX


class TestPerSideLimits:
    def test_limits_defined_for_both_sides(self):
        assert set(JOINT_LIMITS) == {Side.LEFT, Side.RIGHT}

    def test_limit_entries_are_joint_limits_value_objects(self):
        for side in Side:
            assert isinstance(JOINT_LIMITS[side], JointLimits)
            assert JOINT_LIMITS[side].side is side

    def test_limits_are_exactly_ten_dimensional(self):
        for side in Side:
            limits = JOINT_LIMITS[side]
            assert limits.lower.shape == (10,)
            assert limits.upper.shape == (10,)

    def test_lower_le_upper_for_every_joint_and_side(self):
        for side in Side:
            limits = JOINT_LIMITS[side]
            assert np.all(limits.lower <= limits.upper)

    @pytest.mark.parametrize("side,lower,upper", [
        (Side.RIGHT,
         (-0.029670597283903602, -1.642354826126664, 0.0,
          -0.16406094968746698, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
         (1.1213740444063567, 0.04537856055185257, 0.8415977653116657,
          0.0, 1.4835298641951802, 1.4835298641951802,
          0.16929693744344995, 1.4835298641951802,
          0.1850049007113989, 1.4835298641951802)),
        (Side.LEFT,
         (-1.1213740444063567, -0.04537856055185257, -0.8415977653116657,
          0.0, 0.0, 0.0, -0.16929693744344995, 0.0,
          -0.1850049007113989, 0.0),
         (0.029670597283903602, 1.642354826126664, 0.0,
          0.16406094968746698, 1.4835298641951802, 1.4835298641951802,
          0.0, 1.4835298641951802, 0.0, 1.4835298641951802)),
    ])
    def test_authoritative_limit_values_match_model(self, side, lower, upper):
        limits = JOINT_LIMITS[side]
        np.testing.assert_allclose(limits.lower, np.asarray(lower, dtype=float))
        np.testing.assert_allclose(limits.upper, np.asarray(upper, dtype=float))

    def test_limit_arrays_are_immutable(self):
        for side in Side:
            limits = JOINT_LIMITS[side]
            assert not limits.lower.flags.writeable
            assert not limits.upper.flags.writeable

    def test_left_and_right_are_not_identical_objects(self):
        # Per-side limits are distinct value objects (left/right differ in sign).
        assert JOINT_LIMITS[Side.LEFT] is not JOINT_LIMITS[Side.RIGHT]
        assert not np.allclose(JOINT_LIMITS[Side.LEFT].lower,
                               JOINT_LIMITS[Side.RIGHT].lower)
