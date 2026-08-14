"""Coupling derivation tests (passive from active)."""

import math

import pytest

from omnihand_o10_model.contract import (
    ACTIVE_JOINT_BASES,
    FULL_JOINT_BASES,
    PASSIVE_JOINT_BASES,
    active_joint_limits,
    expected_couplings,
    expected_polycoef,
)
from omnihand_o10_model.coupling import (
    CouplingError,
    build_full_state,
    derive_passive,
    evaluate_polycoef,
)
from fixtures import build_mjcf
from omnihand_o10_model.mjcf_validator import validate_mjcf_couplings


def test_evaluate_polycoef_horner():
    # 1 + 2a + 3a^2 at a=2 -> 1 + 4 + 12 = 17
    assert evaluate_polycoef((1.0, 2.0, 3.0, 0.0, 0.0), 2.0) == 17.0


def test_evaluate_polycoef_rejects_non_finite_input():
    with pytest.raises(CouplingError, match="not finite"):
        evaluate_polycoef((0.0, 1.0, 0.0, 0.0, 0.0), float("nan"))


def test_evaluate_polycoef_rejects_wrong_arity():
    with pytest.raises(CouplingError, match="exactly 5"):
        evaluate_polycoef((1.0, 2.0), 0.0)


def test_derive_passive_at_zero_active_is_all_zero():
    # All pinned polycoefs have c0 == 0, so zero active -> zero passive.
    for side in ("left", "right"):
        derived = derive_passive([0.0] * 10, side)
        assert len(derived) == 6
        assert derived == tuple([0.0] * 6)


def test_derive_passive_from_pinned_contract_matches_polynomial():
    side = "right"
    active = [0.0] * 10
    # Drive index_pip (active index 4) to its max.
    active[4] = active_joint_limits(side)[4][1]
    derived = derive_passive(active, side)
    expected_index_dip = evaluate_polycoef(
        expected_polycoef("index_dip", side), active[4]
    )
    idx = PASSIVE_JOINT_BASES.index("index_dip")
    assert math.isclose(derived[idx], expected_index_dip, rel_tol=1e-12)


def test_derive_passive_lands_within_passive_urdf_limit():
    # At active max, the derived finger DIP must not exceed the URDF DIP limit.
    side = "right"
    active_max = [hi for _, hi in active_joint_limits(side)]
    derived = derive_passive(active_max, side)
    finger_dip_limit = 1.7540558982543013
    for value in derived:
        assert -1e-9 <= value <= finger_dip_limit + 1e-6


def test_derive_passive_uses_mjcf_coupling_model():
    side = "left"
    model = validate_mjcf_couplings(build_mjcf(side), side)
    active = [0.3] * 10
    from_contract = derive_passive(active, side)
    from_model = derive_passive(active, side, coupling_model=model)
    assert from_contract == from_model


def test_derive_passive_rejects_wrong_active_length():
    with pytest.raises(CouplingError, match="expected 10 active values"):
        derive_passive([0.0] * 9, "right")


def test_build_full_state_dimension_and_active_positions():
    side = "right"
    active = [0.1, 0.2, 0.3, 0.05, 0.4, 0.4, 0.05, 0.4, 0.05, 0.4]
    full = build_full_state(active, side)
    assert len(full) == 16
    # Active joints appear at their document positions unchanged.
    contract_full = FULL_JOINT_BASES
    for i, base in enumerate(ACTIVE_JOINT_BASES):
        pos = contract_full.index(base)
        assert math.isclose(full[pos], active[i], rel_tol=1e-12)


def test_thumb_dip_derivation_differs_left_right_at_same_thumb_mcp():
    # Same thumb_mcp value, different side -> different thumb_dip (mirroring).
    side_value = 0.6
    right_active = [0.0] * 10
    right_active[2] = side_value  # thumb_mcp
    left_active = list(right_active)
    right_dip = derive_passive(right_active, "right")[PASSIVE_JOINT_BASES.index("thumb_dip")]
    left_dip = derive_passive(left_active, "left")[PASSIVE_JOINT_BASES.index("thumb_dip")]
    assert right_dip != left_dip
