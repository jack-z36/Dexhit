"""Version-locked OmniHand O10 structural contract.

This module is the single in-package source of truth for the O10 model
structure that the URDF/MJCF/provenance validators enforce. It pins:

* the upstream repository and commit (ADR-0007 provenance baseline);
* the side prefix convention and the 10 active joint names/order
  (Spec decision 24: ``thumb_roll, thumb_abad, thumb_mcp, index_abad,
  index_pip, middle_pip, ring_abad, ring_pip, pinky_abad, pinky_pip``);
* the full 16-joint order (10 active + 6 passive, Spec decision 20/23);
* the 6 active->passive coupling relationships and their polynomial
  coefficients read from the MJCF ``equality/joint`` constraints;
* the required palm / root / tip frames;
* per-side joint limits.

The asset values below were read from the pinned upstream commit and are the
contract the real, post-license assets must satisfy. They are NOT the asset
files themselves: no upstream geometry, meshes or generated URDF/MJCF are
vendored into this repository pending license confirmation (ADR-0007,
ARCHITECTURE invariant A12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from omnihand_o10_contracts.joints import (
    ACTIVE_JOINT_NAMES as ACTIVE_JOINT_BASES,
    JOINT_LIMITS,
)
from omnihand_o10_contracts.side import Side

# ---------------------------------------------------------------------------
# Upstream provenance baseline (ADR-0007).
# ---------------------------------------------------------------------------
UPSTREAM_REPO = "https://github.com/manusvr/ManusOmniBridge.git"
UPSTREAM_COMMIT = "f4fd0d913c2151bcb4be0d29fbc02761b9638009"
# The upstream package.xml declares Apache-2.0, but the upstream commit does
# not ship the license body. Redistribution into this repo is therefore
# blocked until the license is confirmed (ADR-0007).
UPSTREAM_DECLARED_LICENSE = "Apache-2.0"
UPSTREAM_LICENSE_CONFIRMED = False
# Path to the O10 description package inside the upstream tree.
UPSTREAM_O10_PACKAGE_PATH = "src/omnihand_description-O10"

# ---------------------------------------------------------------------------
# Logical hand sides and naming convention.
# ---------------------------------------------------------------------------
SIDES: Tuple[str, ...] = ("left", "right")
# Upstream names kinematic joints/links as ``{L,R}_<base>_joint`` /
# ``{L,R}_<base>_link`` (e.g. ``R_thumb_mcp_joint``, ``R_palm``). The prefix
# therefore includes the trailing underscore.
SIDE_PREFIX: Dict[str, str] = {"left": "L_", "right": "R_"}


def side_prefix(side: str) -> str:
    """Return the URDF/MJCF link/joint prefix for a logical side."""
    try:
        return SIDE_PREFIX[side]
    except KeyError as error:  # pragma: no cover - exercised by tests
        raise ValueError(f"unsupported hand side: {side!r}") from error


# ---------------------------------------------------------------------------
# Joint contract. Side-agnostic *base* names; concrete names are produced by
# :func:`joint_name` / :func:`link_name` which prepend the L_/R_ prefix used by
# the upstream assets.
# ---------------------------------------------------------------------------
# Spec decision 24: the 10 actively commanded joints and their fixed order are
# imported from omnihand_o10_contracts, the sole A11 owner.  The alias keeps
# this model package's structural API readable without defining a second list.
N_ACTIVE = len(ACTIVE_JOINT_BASES)  # 10

# Spec decision 20/23: full 16-joint order as it appears in document order in
# the generated URDF. The 6 passive joints (derived, never commanded) are
# interspersed after their driving active joint.
PASSIVE_JOINT_BASES: Tuple[str, ...] = (
    "thumb_pip",
    "thumb_dip",
    "index_dip",
    "middle_dip",
    "ring_dip",
    "pinky_dip",
)
N_PASSIVE = len(PASSIVE_JOINT_BASES)  # 6
N_FULL = N_ACTIVE + N_PASSIVE  # 16

FULL_JOINT_BASES: Tuple[str, ...] = (
    "thumb_roll",
    "thumb_abad",
    "thumb_mcp",
    "thumb_pip",
    "thumb_dip",
    "index_abad",
    "index_pip",
    "index_dip",
    "middle_pip",
    "middle_dip",
    "ring_abad",
    "ring_pip",
    "ring_dip",
    "pinky_abad",
    "pinky_pip",
    "pinky_dip",
)

# Movable URDF joint types that contribute to nq/nv.
MOVABLE_JOINT_TYPES = frozenset({"revolute", "continuous", "prismatic"})


def joint_name(side: str, base: str) -> str:
    """Concrete joint name as it appears in the upstream URDF/MJCF.

    Upstream names the kinematic joints ``{L,R}_{base}_joint``.
    """
    return f"{side_prefix(side)}{base}_joint"


def link_name(side: str, base: str) -> str:
    """Concrete link/body name as it appears in the upstream URDF/MJCF."""
    return f"{side_prefix(side)}{base}_link"


# ---------------------------------------------------------------------------
# Required frames (Spec decision 18; CONTEXT.md "规范 O10 手掌坐标系").
# ---------------------------------------------------------------------------
PALM_FRAME_BASES: Tuple[str, ...] = ("palm",)  # R_palm / L_palm
ROOT_LINK = "base_link"
TIP_FRAME_BASES: Tuple[str, ...] = (
    "thumb_tip",
    "index_tip",
    "middle_tip",
    "ring_tip",
    "pinky_tip",
)


def palm_frame(side: str) -> str:
    """Canonical O10 palm frame name (R_palm / L_palm)."""
    return f"{side_prefix(side)}palm"


def tip_link(side: str, base: str) -> str:
    """Concrete tip link name (e.g. ``R_index_tip``)."""
    return f"{side_prefix(side)}{base}"


# ---------------------------------------------------------------------------
# Active -> passive coupling relationships (Spec decision 21/23).
#
# Each entry says: the passive joint is driven by exactly one active joint via a
# 4th-order polynomial whose 5 finite coefficients are recorded in the MJCF
# ``equality/joint`` element. ``polycoef`` orientation is passive = poly(active):
#     passive_value = c0 + c1*a + c2*a**2 + c3*a**3 + c4*a**4
# where ``a`` is the driving active joint value.
#
# NOTE on MJCF orientation: in the upstream MJCF the equality element lists the
# passive joint as ``joint1`` and the driving active joint as ``joint2``.
# Numerically the stored coefficients describe passive = poly(active); the
# MJCF loader therefore classifies which endpoint is active from the active set
# above and evaluates the polynomial at the active value.
# ---------------------------------------------------------------------------
THUMB_DRIVER = "thumb_mcp"


@dataclass(frozen=True)
class CouplingSpec:
    """One active->passive polynomial coupling relationship."""

    passive: str
    active: str
    # 5 finite coefficients [c0, c1, c2, c3, c4] for passive = poly(active).
    polycoef: Tuple[float, float, float, float, float]
    # Whether this coupling is expected to differ between left and right
    # (because of hand mirroring). Only the thumb_DIP coupling differs.
    side_asymmetric: bool = False


# Coefficients read from the pinned upstream commit.
# Fingers (index/middle/ring/pinky DIP) are identical for both sides.
_FINGER_DIP_COEF = (0.0, 2.192, -1.425, 0.747, -0.167)
# Thumb PIP is linear and identical for both sides.
_THUMB_PIP_COEF = (0.0, 1.33, 0.0, 0.0, 0.0)
# Thumb DIP differs between sides: the quadratic coefficient flips sign.
_THUMB_DIP_COEF_RIGHT = (0.0, 1.846, -0.853, 0.280, 0.0)
_THUMB_DIP_COEF_LEFT = (0.0, 1.846, 0.853, 0.280, 0.0)

# Base-name coupling template (side-agnostic except for thumb_dip, which has two
# coefficient variants). ``expected_polycoef`` resolves the concrete coefficients.
_COUPLING_TEMPLATE: Tuple[Tuple[str, str], ...] = (
    ("thumb_pip", "thumb_mcp"),
    ("thumb_dip", "thumb_mcp"),
    ("index_dip", "index_pip"),
    ("middle_dip", "middle_pip"),
    ("ring_dip", "ring_pip"),
    ("pinky_dip", "pinky_pip"),
)


def expected_polycoef(passive_base: str, side: str) -> Tuple[float, ...]:
    """Return the pinned polynomial coefficients for a coupling."""
    if passive_base == "thumb_pip":
        return _THUMB_PIP_COEF
    if passive_base == "thumb_dip":
        return _THUMB_DIP_COEF_LEFT if side == "left" else _THUMB_DIP_COEF_RIGHT
    if passive_base.endswith("_dip"):
        return _FINGER_DIP_COEF
    raise KeyError(f"no pinned polycoef for passive joint base {passive_base!r}")


def expected_couplings(side: str) -> Tuple[CouplingSpec, ...]:
    """Return the 6 expected active->passive couplings for a side."""
    specs: List[CouplingSpec] = []
    for passive_base, active_base in _COUPLING_TEMPLATE:
        specs.append(
            CouplingSpec(
                passive=passive_base,
                active=active_base,
                polycoef=expected_polycoef(passive_base, side),
                side_asymmetric=(passive_base == "thumb_dip"),
            )
        )
    return tuple(specs)


def expected_coupling_count() -> int:
    """Fixed number of active->passive couplings (Spec decision 21)."""
    return 6


# ---------------------------------------------------------------------------
# Per-side joint limits for the 10 active joints (Spec decision 24).
#
# Read from the pinned upstream URDF. Limits are mirrored between sides. These
# are the authority for the URDF limit check; they intentionally match the
# limits enforced by omnihand_o10_control (which owns the runtime command
# contract) so the model and command sides cannot drift silently.
# ---------------------------------------------------------------------------
# (lower, upper) per active joint base, read from the pinned upstream URDF for
# BOTH sides. Note the mirroring is NOT uniform: only the thumb joints and the
# *_abad joints flip sign between left and right; the *_pip flexion joints keep
# the same non-negative limits on both sides. The values below are exact (not
# rounded) so the model-side limit check and the omnihand_o10_control command
# limit check (which rounds for readability) cannot drift.
_RIGHT_LIMITS: Tuple[Tuple[float, float], ...] = tuple(
    (float(lower), float(upper))
    for lower, upper in zip(JOINT_LIMITS[Side.RIGHT].lower, JOINT_LIMITS[Side.RIGHT].upper)
)

_LEFT_LIMITS: Tuple[Tuple[float, float], ...] = tuple(
    (float(lower), float(upper))
    for lower, upper in zip(JOINT_LIMITS[Side.LEFT].lower, JOINT_LIMITS[Side.LEFT].upper)
)


def active_joint_limits(side: str) -> Tuple[Tuple[float, float], ...]:
    """Return the (lower, upper) limits for the 10 active joints, in order."""
    resolved = Side.from_value(side)
    limits = JOINT_LIMITS[resolved]
    return tuple(
        (float(lower), float(upper))
        for lower, upper in zip(limits.lower, limits.upper)
    )


def active_joint_names(side: str) -> Tuple[str, ...]:
    """Concrete active joint names in the fixed command order."""
    return tuple(joint_name(side, base) for base in ACTIVE_JOINT_BASES)


def full_joint_names(side: str) -> Tuple[str, ...]:
    """Concrete 16-joint names in URDF document order."""
    return tuple(joint_name(side, base) for base in FULL_JOINT_BASES)


def passive_joint_names(side: str) -> Tuple[str, ...]:
    """Concrete 6 passive joint names."""
    return tuple(joint_name(side, base) for base in PASSIVE_JOINT_BASES)


def required_urdf_links(side: str) -> Dict[str, str]:
    """Map of required frame role -> concrete link name for structural checks."""
    prefix = side_prefix(side)
    links: Dict[str, str] = {
        "root": ROOT_LINK,
        "palm": palm_frame(side),
    }
    for base in TIP_FRAME_BASES:
        links[f"tip:{base}"] = f"{prefix}{base}"
    return links


@dataclass(frozen=True)
class SideContract:
    """Fully resolved concrete contract for one logical side."""

    side: str
    active_joints: Tuple[str, ...]
    passive_joints: Tuple[str, ...]
    full_joints: Tuple[str, ...]
    couplings: Tuple[CouplingSpec, ...] = field(default_factory=tuple)
    active_limits: Tuple[Tuple[float, float], ...] = field(default_factory=tuple)
    required_links: Dict[str, str] = field(default_factory=dict)

    @property
    def active_joint_set(self) -> frozenset:
        return frozenset(self.active_joints)

    @property
    def passive_joint_set(self) -> frozenset:
        return frozenset(self.passive_joints)


def side_contract(side: str) -> SideContract:
    """Build the fully resolved contract for one logical side."""
    if side not in SIDES:
        raise ValueError(f"unsupported hand side: {side!r}")
    return SideContract(
        side=side,
        active_joints=active_joint_names(side),
        passive_joints=passive_joint_names(side),
        full_joints=full_joint_names(side),
        couplings=expected_couplings(side),
        active_limits=active_joint_limits(side),
        required_links=required_urdf_links(side),
    )
