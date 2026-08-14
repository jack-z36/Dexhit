"""MJCF coupling loader/validator tests.

Proves the strict 6-coupling / finite-coefficient / left-right-thumb-difference
checks accept good synthetic input and reject bad input (Spec decision 21,
testing decision 12).
"""

import pytest

from omnihand_o10_model.mjcf_validator import (
    MjcfValidationError,
    assert_thumb_difference_left_right,
    parse_mjcf_couplings,
    validate_mjcf_couplings,
)
from omnihand_o10_model.contract import expected_couplings, expected_polycoef
from fixtures import build_mjcf, build_mjcf_with_thumb_dip_coef


def test_good_synthetic_mjcf_validates_both_sides():
    for side in ("left", "right"):
        xml = build_mjcf(side)
        model = validate_mjcf_couplings(xml, side)
        assert len(model.couplings) == 6
        # Each coupling stores 5 finite coefficients in passive=poly(active) form.
        for entry in model.couplings:
            assert len(entry.polycoef) == 5


def test_root_must_be_mujoco():
    with pytest.raises(MjcfValidationError, match="root element must be <mujoco>"):
        parse_mjcf_couplings("<robot/>", "right")


def test_missing_equality_section_rejected():
    xml = "<mujoco><worldbody/></mujoco>"
    with pytest.raises(MjcfValidationError, match="no <equality> section"):
        parse_mjcf_couplings(xml, "right")


def test_wrong_coupling_count_rejected():
    xml = build_mjcf("right", drop_coupling="pinky_dip")
    with pytest.raises(MjcfValidationError, match="expected exactly 6"):
        parse_mjcf_couplings(xml, "right")


def test_extra_coupling_rejected():
    xml = build_mjcf("right", extra_coupling={
        "joint1": "R_pinky_dip_joint", "joint2": "R_pinky_abad_joint",
    })
    with pytest.raises(MjcfValidationError, match="expected exactly 6"):
        parse_mjcf_couplings(xml, "right")


def test_unknown_endpoint_names_rejected():
    # Neither endpoint is in the active/passive set.
    xml = build_mjcf("right", extra_coupling={
        "joint1": "nope1", "joint2": "nope2",
    })
    # Replacing one valid coupling with a bogus one keeps the count at 6 only if
    # we drop one and add one; here we add -> count becomes 7. Instead build a
    # targeted override that swaps a real coupling's endpoints.
    override = list(expected_couplings("right"))
    override[0] = type(override[0])(
        passive="bogus_passive", active="bogus_active",
        polycoef=override[0].polycoef, side_asymmetric=False,
    )
    xml = build_mjcf("right", coupling_override=override)
    with pytest.raises(MjcfValidationError, match="exactly one active and one passive"):
        parse_mjcf_couplings(xml, "right")


def test_wrong_polycoef_count_rejected():
    xml = build_mjcf("right", polycoef_count_for="index_dip", polycoef_count=4)
    with pytest.raises(MjcfValidationError, match="exactly 5 finite coefficients"):
        parse_mjcf_couplings(xml, "right")


def test_non_finite_polycoef_rejected():
    xml = build_mjcf("right", bad_polycoef_for="index_dip",
                     bad_polycoef=(0.0, 2.192, float("nan"), 0.747, -0.167))
    with pytest.raises(MjcfValidationError, match="not finite"):
        parse_mjcf_couplings(xml, "right")


def test_non_numeric_polycoef_rejected():
    xml = build_mjcf("right", bad_polycoef_for="index_dip",
                     bad_polycoef=(0.0, "abc", 0.0, 0.0, 0.0))  # type: ignore
    with pytest.raises(MjcfValidationError, match="is not a number"):
        parse_mjcf_couplings(xml, "right")


def test_duplicate_coupling_rejected():
    # Keep the count at 6 but duplicate one coupling's endpoints and drop a
    # different one, so the count gate passes and the uniqueness gate fires.
    from omnihand_o10_model.contract import CouplingSpec, expected_couplings
    specs = list(expected_couplings("right"))
    # Replace pinky_dip coupling with a duplicate of the thumb_pip coupling.
    thumb_pip_spec = next(s for s in specs if s.passive == "thumb_pip")
    specs = [s for s in specs if s.passive != "pinky_dip"]
    specs.append(CouplingSpec(
        passive=thumb_pip_spec.passive, active=thumb_pip_spec.active,
        polycoef=thumb_pip_spec.polycoef, side_asymmetric=False,
    ))
    xml = build_mjcf("right", coupling_override=specs)
    with pytest.raises(MjcfValidationError, match="driven by more than one active joint|duplicate coupling"):
        parse_mjcf_couplings(xml, "right")


def test_polycoef_value_mismatch_rejected():
    # Right polycoef that disagrees with the pinned contract.
    xml = build_mjcf("right", bad_polycoef_for="index_dip",
                     bad_polycoef=(0.0, 1.0, 0.0, 0.0, 0.0))
    with pytest.raises(MjcfValidationError, match="polycoef mismatch"):
        validate_mjcf_couplings(xml, "right")


def test_polynomial_orientation_is_passive_from_active():
    # The parsed coupling stores coefficients in passive=poly(active) form and
    # matches the pinned contract; evaluating at active max lands within the
    # passive DIP URDF limit (proving the orientation, not its inverse).
    from omnihand_o10_model.coupling import evaluate_polycoef
    model = validate_mjcf_couplings(build_mjcf("right"), "right")
    coef = model.polycoef_for("R_index_dip_joint")
    assert coef == expected_polycoef("index_dip", "right")
    at_zero = evaluate_polycoef(coef, 0.0)
    assert at_zero == 0.0  # c0 == 0
    # passive DIP at index_pip max must be <= its URDF limit (1.7540...).
    at_max = evaluate_polycoef(coef, 1.4835298641951802)
    assert 0.0 <= at_max <= 1.7540558982543013


def test_thumb_difference_detected_left_vs_right():
    left = validate_mjcf_couplings(build_mjcf("left"), "left")
    right = validate_mjcf_couplings(build_mjcf("right"), "right")
    assert_thumb_difference_left_right(left, right)


def test_thumb_difference_missing_when_left_uses_right_coef():
    # If the left MJCF carries the RIGHT thumb_dip polycoef, the L/R difference
    # is lost. The cross-side check catches it when fed parsed models (the
    # single-side polycoef-value check would also reject it, so we bypass it
    # here to exercise the cross-side invariant directly).
    right_coef = expected_polycoef("thumb_dip", "right")
    left_xml = build_mjcf_with_thumb_dip_coef("left", right_coef)
    right_xml = build_mjcf("right")
    left = parse_mjcf_couplings(left_xml, "left")
    right = parse_mjcf_couplings(right_xml, "right")
    with pytest.raises(MjcfValidationError, match="thumb_dip polycoef is identical"):
        assert_thumb_difference_left_right(left, right)
