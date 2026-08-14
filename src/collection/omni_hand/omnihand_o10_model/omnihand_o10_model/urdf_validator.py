"""Structural validation of an OmniHand O10 generated URDF.

Enforces Spec decision 20 ("URDF is the geometry/joint/limit/palm/tip source;
Pinocchio loads with mimic disabled and asserts nq=nv=16") and testing
decision 12, without building the kinematic model. The 16-dimension claim is
proven structurally: when mimic is disabled, ``nq == nv ==`` the number of
movable joints, so the check counts movable joints and verifies their names and
order.

A pinocchio-driven ``model.nq == 16`` assertion is a separate, BLOCKED_ENV
check (see :mod:`omnihand_o10_model.pinocchio_model`); it is not faked here.
"""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Union

from .contract import (
    MOVABLE_JOINT_TYPES,
    N_FULL,
    SideContract,
    side_contract,
)


class UrdfValidationError(Exception):
    """Raised when the URDF does not satisfy the O10 structural contract."""


@dataclass
class UrdfStructure:
    """Parsed structural snapshot of a URDF, for diagnostics."""

    movable_joints: List[str] = field(default_factory=list)
    joint_types: Dict[str, str] = field(default_factory=dict)
    joint_limits: Dict[str, "tuple[float, float]"] = field(default_factory=dict)
    mimic_joints: Dict[str, str] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)


def _looks_like_existing_path(source: Union[str, os.PathLike]) -> bool:
    try:
        return Path(source).is_file()
    except (OSError, ValueError):
        return False


def _parse(source: Union[str, os.PathLike, ET.Element]) -> ET.Element:
    if isinstance(source, ET.Element):
        return source
    if isinstance(source, (str, os.PathLike)) and _looks_like_existing_path(source):
        try:
            return ET.parse(source).getroot()
        except ET.ParseError as error:
            raise UrdfValidationError(f"URDF is not well-formed XML: {error}") from error
    # Treat as an XML string.
    try:
        return ET.fromstring(source)
    except ET.ParseError as error:
        raise UrdfValidationError(f"URDF is not well-formed XML: {error}") from error


def _limit_tuple(joint_elem: ET.Element) -> "tuple[float, float]":
    limit = joint_elem.find("limit")
    if limit is None:
        raise UrdfValidationError(
            f"joint {joint_elem.get('name')!r} has no <limit>"
        )
    try:
        lower = float(limit.get("lower", "0"))
        upper = float(limit.get("upper", "0"))
    except (TypeError, ValueError) as error:
        raise UrdfValidationError(
            f"joint {joint_elem.get('name')!r} has non-numeric limits"
        ) from error
    return lower, upper


def parse_urdf_structure(source: Union[str, os.PathLike, ET.Element]) -> UrdfStructure:
    """Parse a URDF into a structural snapshot without O10-specific assertions."""
    root = _parse(source)
    if root.tag != "robot":
        raise UrdfValidationError(f"URDF root element must be <robot>, got <{root.tag}>")

    structure = UrdfStructure()
    structure.links = [elem.get("name") for elem in root.findall("link")
                       if elem.get("name")]

    for joint_elem in root.findall("joint"):
        name = joint_elem.get("name")
        jtype = joint_elem.get("type")
        if jtype in MOVABLE_JOINT_TYPES:
            structure.movable_joints.append(name)
            structure.joint_types[name] = jtype
            structure.joint_limits[name] = _limit_tuple(joint_elem)
        mimic = joint_elem.find("mimic")
        if mimic is not None and name is not None:
            structure.mimic_joints[name] = mimic.get("joint")
    return structure


def validate_urdf(
    source: Union[str, os.PathLike, ET.Element],
    side: str,
    *,
    contract: Union[SideContract, None] = None,
) -> UrdfStructure:
    """Validate a side's generated URDF against the O10 contract.

    Raises :class:`UrdfValidationError` with a precise reason on any structural
    mismatch. Returns the parsed :class:`UrdfStructure` on success.
    """
    contract = contract or side_contract(side)
    structure = parse_urdf_structure(source)

    _assert_dimension(structure, contract)
    _assert_joint_names_and_order(structure, contract)
    _assert_active_joint_limits(structure, contract)
    _assert_required_frames(structure, contract)

    return structure


def _assert_dimension(structure: UrdfStructure, contract: SideContract) -> None:
    """Assert nq == nv == 16 by counting movable joints (mimic disabled)."""
    count = len(structure.movable_joints)
    if count != N_FULL:
        raise UrdfValidationError(
            f"expected {N_FULL} movable joints (nq=nv={N_FULL} with mimic "
            f"disabled) for side {contract.side!r}, found {count}: "
            f"{structure.movable_joints}"
        )


def _assert_joint_names_and_order(
    structure: UrdfStructure, contract: SideContract
) -> None:
    expected = list(contract.full_joints)
    actual = structure.movable_joints
    if actual != expected:
        expected_set = set(expected)
        actual_set = set(actual)
        missing = expected_set - actual_set
        extra = actual_set - expected_set
        if missing or extra:
            raise UrdfValidationError(
                f"joint name set mismatch for side {contract.side!r}: "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        # Same set, different order.
        raise UrdfValidationError(
            f"joint order mismatch for side {contract.side!r}: "
            f"expected {expected}, got {actual}"
        )
    non_revolute = {
        name: structure.joint_types[name]
        for name in actual
        if structure.joint_types[name] != "revolute"
    }
    if non_revolute:
        raise UrdfValidationError(
            f"all O10 joints must be revolute, found: {non_revolute}"
        )


def _assert_active_joint_limits(
    structure: UrdfStructure, contract: SideContract
) -> None:
    for base_index, (joint, (low, high)) in enumerate(
        zip(contract.active_joints, contract.active_limits)
    ):
        if joint not in structure.joint_limits:
            raise UrdfValidationError(
                f"active joint {joint!r} has no limits in the URDF"
            )
        actual_low, actual_high = structure.joint_limits[joint]
        if not math.isclose(actual_low, low, rel_tol=1e-6, abs_tol=1e-9) or \
           not math.isclose(actual_high, high, rel_tol=1e-6, abs_tol=1e-9):
            raise UrdfValidationError(
                f"active joint {joint!r} limit mismatch: "
                f"declared [{actual_low}, {actual_high}], "
                f"contract [{low}, {high}]"
            )


def _assert_required_frames(structure: UrdfStructure, contract: SideContract) -> None:
    link_set = set(structure.links)
    for role, name in contract.required_links.items():
        if name not in link_set:
            raise UrdfValidationError(
                f"required frame {role!r} ({name!r}) not found in URDF links"
            )
