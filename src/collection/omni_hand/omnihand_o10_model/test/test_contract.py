"""Contract invariants for the pinned O10 structural contract."""

import pytest

from omnihand_o10_model.contract import (
    ACTIVE_JOINT_BASES,
    FULL_JOINT_BASES,
    N_ACTIVE,
    N_FULL,
    N_PASSIVE,
    PASSIVE_JOINT_BASES,
    SIDES,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
    active_joint_limits,
    active_joint_names,
    expected_coupling_count,
    expected_couplings,
    full_joint_names,
    palm_frame,
    required_urdf_links,
    side_contract,
)


def test_dimensions_match_spec():
    # Spec decisions 23/24: 10 active, 6 passive, 16 full.
    assert N_ACTIVE == 10
    assert N_PASSIVE == 6
    assert N_FULL == 16
    assert len(ACTIVE_JOINT_BASES) == 10
    assert len(PASSIVE_JOINT_BASES) == 6
    assert len(FULL_JOINT_BASES) == 16


def test_active_order_matches_spec_decision_24():
    assert ACTIVE_JOINT_BASES == (
        "thumb_roll", "thumb_abad", "thumb_mcp",
        "index_abad", "index_pip",
        "middle_pip",
        "ring_abad", "ring_pip",
        "pinky_abad", "pinky_pip",
    )


def test_full_joint_order_has_active_before_its_passive():
    # Each passive joint appears immediately after the active joint driving it
    # in the URDF document order, so the contract's full order is well-formed.
    driver_of = {spec.passive: spec.active for spec in expected_couplings("right")}
    for passive in PASSIVE_JOINT_BASES:
        driver = driver_of[passive]
        assert FULL_JOINT_BASES.index(passive) > FULL_JOINT_BASES.index(driver)


def test_active_set_and_passive_set_are_disjoint_and_complete():
    for side in SIDES:
        contract = side_contract(side)
        assert len(contract.active_joints) == N_ACTIVE
        assert len(contract.passive_joints) == N_PASSIVE
        assert len(contract.full_joints) == N_FULL
        assert set(contract.active_joints) & set(contract.passive_joints) == set()
        assert set(contract.full_joints) == set(contract.active_joints) | set(contract.passive_joints)


def test_six_unique_couplings_each_one_active_one_passive():
    for side in SIDES:
        couplings = expected_couplings(side)
        assert len(couplings) == expected_coupling_count() == 6
        passives = [c.passive for c in couplings]
        assert len(set(passives)) == 6  # uniqueness
        for spec in couplings:
            assert spec.active in ACTIVE_JOINT_BASES
            assert spec.passive in PASSIVE_JOINT_BASES
            assert len(spec.polycoef) == 5


def test_thumb_dip_is_the_only_side_asymmetric_coupling():
    for side in SIDES:
        asymmetric = [c.passive for c in expected_couplings(side) if c.side_asymmetric]
        assert asymmetric == ["thumb_dip"]


def test_thumb_dip_polycoef_differs_left_right_others_identical():
    def coef(side, passive):
        return next(c.polycoef for c in expected_couplings(side) if c.passive == passive)
    # thumb_dip must differ (quadratic sign flip).
    assert coef("left", "thumb_dip") != coef("right", "thumb_dip")
    # All other couplings must be identical L/R.
    for passive in ("thumb_pip", "index_dip", "middle_dip", "ring_dip", "pinky_dip"):
        assert coef("left", passive) == coef("right", passive)


def test_joint_and_link_names_use_upstream_prefix():
    for side in SIDES:
        prefix = "R_" if side == "right" else "L_"
        assert active_joint_names(side)[0] == f"{prefix}thumb_roll_joint"
        assert palm_frame(side) == f"{prefix}palm"


def test_required_frames_present_for_both_sides():
    for side in SIDES:
        links = required_urdf_links(side)
        assert links["root"] == "base_link"
        assert links["palm"].endswith("_palm")
        tips = [v for k, v in links.items() if k.startswith("tip:")]
        assert len(tips) == 5


def test_pip_limits_not_mirrored_but_abad_and_thumb_are():
    # Real URDF: *_pip flexion keeps the same limits L/R; thumb and *_abad mirror.
    for base in ACTIVE_JOINT_BASES:
        right = active_joint_limits("right")[ACTIVE_JOINT_BASES.index(base)]
        left = active_joint_limits("left")[ACTIVE_JOINT_BASES.index(base)]
        if base.endswith("_pip"):
            assert right == left, f"{base} should NOT mirror"
        else:
            assert right == (-left[1], -left[0]), f"{base} should mirror"


def test_upstream_provenance_baseline_pinned():
    assert UPSTREAM_REPO == "https://github.com/manusvr/ManusOmniBridge.git"
    assert UPSTREAM_COMMIT == "f4fd0d913c2151bcb4be0d29fbc02761b9638009"


def test_limits_match_control_package_rounded_values():
    # The model-side exact limits must agree with omnihand_o10_control's command
    # limits (which are rounded for readability) so the two sides cannot drift
    # (decision 24). The control package mixes 2- and 4-decimal rounding, so we
    # compare within the rounding granularity rather than exact equality.
    right = active_joint_limits("right")
    control_right_min = [-0.03, -1.64, 0.0, -0.16, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    control_right_max = [1.12, 0.05, 0.8416, 0.0, 1.48, 1.48, 0.17, 1.48, 0.19, 1.48]
    for (lo, hi), c_lo, c_hi in zip(right, control_right_min, control_right_max):
        assert abs(lo - c_lo) < 0.011
        assert abs(hi - c_hi) < 0.011


def test_invalid_side_rejected():
    with pytest.raises(ValueError, match="unsupported hand side"):
        side_contract("middle")
    with pytest.raises(ValueError, match="unsupported hand side"):
        active_joint_limits("middle")
