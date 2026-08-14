"""Strict MJCF coupling loader/validator for the OmniHand O10.

Spec decision 21: the MJCF is only a data source for the six active->passive
``equality/joint`` polynomial couplings. The strict loader validates:

* exactly six ``equality/joint`` constraints are present;
* each endpoint name maps to exactly one active and one passive joint from the
  pinned contract, with the expected (active, passive) pair;
* every passive joint is driven by exactly one active joint (uniqueness);
* each coupling declares exactly five finite ``polycoef`` values;
* the polynomial coefficients match the pinned values, including the
  side-asymmetric thumb DIP coupling (the left/right thumb difference).

The loader never loads the MJCF as a MuJoCo online model and never assumes
MuJoCo auto-eliminates the passive joints: it records the polynomial in the
``passive = poly(active)`` orientation so passive joints are derived from the
active variables at runtime.
"""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Union

from .contract import (
    CouplingSpec,
    N_PASSIVE,
    SIDE_PREFIX,
    expected_coupling_count,
    expected_couplings,
    side_contract,
)


class MjcfValidationError(Exception):
    """Raised when the MJCF does not satisfy the O10 coupling contract."""


@dataclass(frozen=True)
class CouplingEntry:
    """A parsed and re-oriented active->passive coupling.

    ``polycoef`` is stored in the ``passive = poly(active)`` orientation:
    ``passive = c0 + c1*a + c2*a**2 + c3*a**3 + c4*a**4`` with ``a`` the value
    of the driving active joint.
    """

    active_joint: str
    passive_joint: str
    polycoef: Tuple[float, float, float, float, float]
    # Raw orientation from the file for diagnostics.
    raw_joint1: str
    raw_joint2: str


@dataclass
class MjcfCouplingModel:
    """Parsed MJCF coupling model for one side."""

    side: str
    couplings: List[CouplingEntry] = field(default_factory=list)

    @property
    def passive_to_active(self) -> Dict[str, str]:
        return {entry.passive_joint: entry.active_joint for entry in self.couplings}

    def polycoef_for(self, passive_joint: str) -> Tuple[float, ...]:
        for entry in self.couplings:
            if entry.passive_joint == passive_joint:
                return entry.polycoef
        raise KeyError(passive_joint)


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
            raise MjcfValidationError(f"MJCF is not well-formed XML: {error}") from error
    try:
        return ET.fromstring(source)
    except ET.ParseError as error:
        raise MjcfValidationError(f"MJCF is not well-formed XML: {error}") from error


def _parse_polycoef(raw: str, coupling_id: str) -> Tuple[float, float, float, float, float]:
    tokens = raw.split()
    if len(tokens) != 5:
        raise MjcfValidationError(
            f"coupling {coupling_id!r}: polycoef must have exactly 5 finite "
            f"coefficients, got {len(tokens)}: {raw!r}"
        )
    values: List[float] = []
    for token in tokens:
        try:
            value = float(token)
        except ValueError as error:
            raise MjcfValidationError(
                f"coupling {coupling_id!r}: polycoef token {token!r} is not a number"
            ) from error
        if not math.isfinite(value):
            raise MjcfValidationError(
                f"coupling {coupling_id!r}: polycoef token {token!r} is not finite"
            )
        values.append(value)
    return (values[0], values[1], values[2], values[3], values[4])


def _coefficients_equal(
    left: Sequence[float], right: Sequence[float], *, tol: float = 1e-9
) -> bool:
    if len(left) != len(right):
        return False
    return all(math.isclose(a, b, rel_tol=0.0, abs_tol=tol) for a, b in zip(left, right))


def _concrete_coupling_names(side: str, spec: CouplingSpec) -> Tuple[str, str]:
    prefix = SIDE_PREFIX[side]
    active = f"{prefix}{spec.active}_joint"
    passive = f"{prefix}{spec.passive}_joint"
    return active, passive


def parse_mjcf_couplings(
    source: Union[str, os.PathLike, ET.Element],
    side: str,
) -> MjcfCouplingModel:
    """Parse and re-orient the six couplings from a side's MJCF.

    Performs structural/parse-level checks (count, name classification,
    uniqueness, finite polycoef). Use :func:`validate_mjcf_couplings` for the
    full pinned-contract check.
    """
    contract = side_contract(side)
    root = _parse(source)
    if root.tag != "mujoco":
        raise MjcfValidationError(f"MJCF root element must be <mujoco>, got <{root.tag}>")

    equality = root.find("equality")
    if equality is None:
        raise MjcfValidationError(f"side {side!r} MJCF has no <equality> section")

    joint_constraints = equality.findall("joint")
    if len(joint_constraints) != expected_coupling_count():
        raise MjcfValidationError(
            f"side {side!r}: expected exactly {expected_coupling_count()} "
            f"equality/joint couplings, found {len(joint_constraints)}"
        )

    active_set = contract.active_joint_set
    passive_set = contract.passive_joint_set
    model = MjcfCouplingModel(side=side)
    seen_passive: Dict[str, str] = {}
    seen_pairs: set = set()

    for elem in joint_constraints:
        j1 = elem.get("joint1")
        j2 = elem.get("joint2")
        poly_raw = elem.get("polycoef")
        if j1 is None or j2 is None:
            raise MjcfValidationError(
                f"equality/joint must define joint1 and joint2; got j1={j1!r} j2={j2!r}"
            )
        if poly_raw is None:
            raise MjcfValidationError(
                f"coupling joint1={j1!r} joint2={j2!r} has no polycoef attribute"
            )

        endpoints = {j1, j2}
        active_hits = endpoints & active_set
        passive_hits = endpoints & passive_set
        if len(active_hits) != 1 or len(passive_hits) != 1:
            raise MjcfValidationError(
                f"side {side!r}: coupling joint1={j1!r} joint2={j2!r} must map to "
                f"exactly one active and one passive joint; "
                f"active_hits={sorted(active_hits)} passive_hits={sorted(passive_hits)}"
            )
        active_joint = next(iter(active_hits))
        passive_joint = next(iter(passive_hits))

        pair = (active_joint, passive_joint)
        if pair in seen_pairs:
            raise MjcfValidationError(
                f"side {side!r}: duplicate coupling {active_joint}->{passive_joint}"
            )
        if passive_joint in seen_passive:
            raise MjcfValidationError(
                f"side {side!r}: passive joint {passive_joint!r} is driven by more "
                f"than one active joint "
                f"({seen_passive[passive_joint]} and {active_joint})"
            )
        seen_pairs.add(pair)
        seen_passive[passive_joint] = active_joint

        poly = _parse_polycoef(poly_raw, f"{j1}->{j2}")
        model.couplings.append(
            CouplingEntry(
                active_joint=active_joint,
                passive_joint=passive_joint,
                polycoef=poly,
                raw_joint1=j1,
                raw_joint2=j2,
            )
        )

    if len(model.couplings) != N_PASSIVE:
        raise MjcfValidationError(
            f"side {side!r}: expected {N_PASSIVE} unique couplings, "
            f"got {len(model.couplings)}"
        )
    return model


def validate_mjcf_couplings(
    source: Union[str, os.PathLike, ET.Element],
    side: str,
) -> MjcfCouplingModel:
    """Parse a side's MJCF and enforce the full pinned coupling contract."""
    model = parse_mjcf_couplings(source, side)

    expected: Dict[Tuple[str, str], CouplingSpec] = {}
    for spec in expected_couplings(side):
        active, passive = _concrete_coupling_names(side, spec)
        expected[(active, passive)] = spec

    actual_pairs = {(entry.active_joint, entry.passive_joint) for entry in model.couplings}
    expected_pairs = set(expected)
    if actual_pairs != expected_pairs:
        missing = expected_pairs - actual_pairs
        extra = actual_pairs - expected_pairs
        raise MjcfValidationError(
            f"side {side!r}: coupling set mismatch "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )

    for entry in model.couplings:
        spec = expected[(entry.active_joint, entry.passive_joint)]
        if not _coefficients_equal(entry.polycoef, spec.polycoef):
            raise MjcfValidationError(
                f"side {side!r}: polycoef mismatch for {spec.active}->{spec.passive}: "
                f"declared {entry.polycoef}, contract {spec.polycoef}"
            )
    return model


def assert_thumb_difference_left_right(
    left_model: MjcfCouplingModel,
    right_model: MjcfCouplingModel,
) -> None:
    """Assert the thumb coupling captures the left/right difference.

    The thumb DIP coupling is the side-asymmetric one (its quadratic
    coefficient flips sign between left and right). All other couplings,
    including the linear thumb PIP coupling, must be identical between sides.
    """

    def find(model: MjcfCouplingModel, side: str, passive_base: str) -> Tuple[float, ...]:
        prefix = SIDE_PREFIX[side]
        passive = f"{prefix}{passive_base}_joint"
        return model.polycoef_for(passive)

    left_thumb_dip = find(left_model, "left", "thumb_dip")
    right_thumb_dip = find(right_model, "right", "thumb_dip")
    if _coefficients_equal(left_thumb_dip, right_thumb_dip):
        raise MjcfValidationError(
            "left/right thumb difference not captured: thumb_dip polycoef is "
            f"identical on both sides ({left_thumb_dip})"
        )

    identical_bases = ("thumb_pip", "index_dip", "middle_dip", "ring_dip", "pinky_dip")
    for base in identical_bases:
        left_coef = find(left_model, "left", base)
        right_coef = find(right_model, "right", base)
        if not _coefficients_equal(left_coef, right_coef):
            raise MjcfValidationError(
                f"coupling {base!r} unexpectedly differs between left and right: "
                f"left={left_coef} right={right_coef}"
            )
