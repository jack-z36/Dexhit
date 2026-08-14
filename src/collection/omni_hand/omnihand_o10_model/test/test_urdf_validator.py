"""URDF structural validator tests.

Proves the 16-dimension / active-order / limits / frames checks accept good
synthetic input and reject bad input (Spec testing decision 12).
"""

import pytest

from omnihand_o10_model.urdf_validator import (
    UrdfValidationError,
    parse_urdf_structure,
    validate_urdf,
)
from fixtures import build_urdf


def test_good_synthetic_urdf_validates_both_sides():
    for side in ("left", "right"):
        xml = build_urdf(side)
        structure = validate_urdf(xml, side)
        assert len(structure.movable_joints) == 16
        assert len(structure.mimic_joints) == 6
        assert all(t == "revolute" for t in structure.joint_types.values())


def test_root_must_be_robot_element():
    with pytest.raises(UrdfValidationError, match="root element must be <robot>"):
        parse_urdf_structure("<mujoco/>")


def test_malformed_xml_rejected():
    with pytest.raises(UrdfValidationError, match="not well-formed"):
        validate_urdf("<robot><broken", "right")


def test_wrong_dimension_rejected():
    # Drop one joint -> 15 movable joints instead of 16.
    xml = build_urdf("right", drop_joint="pinky_pip")
    with pytest.raises(UrdfValidationError, match="expected 16 movable joints"):
        validate_urdf(xml, "right")


def test_extra_joint_rejected():
    # An extra movable joint pushes the dimension to 17; the dimension gate
    # fires before the name-set check (both are valid rejections).
    xml = build_urdf("right", extra_joint="bogus_joint")
    with pytest.raises(UrdfValidationError, match="expected 16 movable joints"):
        validate_urdf(xml, "right")


def test_joint_order_mismatch_rejected():
    from omnihand_o10_model.contract import FULL_JOINT_BASES
    # Same set, swapped order (move thumb_pip before thumb_mcp).
    reordered = list(FULL_JOINT_BASES)
    i_mcp = reordered.index("thumb_mcp")
    i_pip = reordered.index("thumb_pip")
    reordered[i_mcp], reordered[i_pip] = reordered[i_pip], reordered[i_mcp]
    xml = build_urdf("right", joint_order=reordered)
    with pytest.raises(UrdfValidationError, match="joint order mismatch"):
        validate_urdf(xml, "right")


def test_non_revolute_joint_rejected():
    xml = build_urdf("right", joint_type_override={"thumb_roll": "continuous"})
    with pytest.raises(UrdfValidationError, match="all O10 joints must be revolute"):
        validate_urdf(xml, "right")


def test_wrong_active_limit_rejected():
    xml = build_urdf("right", bad_limit_for="thumb_roll",
                     bad_limit_value=("-10.0", "10.0"))
    with pytest.raises(UrdfValidationError, match="limit mismatch"):
        validate_urdf(xml, "right")


def test_missing_palm_frame_rejected():
    xml = build_urdf("right", missing_link="palm")
    with pytest.raises(UrdfValidationError, match="required frame 'palm'"):
        validate_urdf(xml, "right")


def test_missing_tip_frame_rejected():
    xml = build_urdf("right", missing_link="index_tip")
    with pytest.raises(UrdfValidationError, match="required frame 'tip:index_tip'"):
        validate_urdf(xml, "right")


def test_missing_root_link_rejected():
    xml = build_urdf("right", missing_link="root")
    with pytest.raises(UrdfValidationError, match="required frame 'root'"):
        validate_urdf(xml, "right")
