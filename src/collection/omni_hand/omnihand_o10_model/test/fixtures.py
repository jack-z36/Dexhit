"""Synthetic URDF/MJCF fixture builders for structural validator tests.

These build *tiny, contract-conforming* O10 snippets programmatically from the
pinned contract so that the structural validators can be shown to accept good
input and reject bad input without depending on the (not-yet-vendored, license
pending) upstream assets. They are deliberately minimal: just enough joints,
links and couplings to exercise the 16-dim / 6-coupling / finite-coefficient
checks.

The MJCF orientation matches the real upstream assets: ``joint1`` holds the
passive joint name and ``joint2`` holds the driving active joint name, with
``polycoef`` describing ``passive = poly(active)``.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

from omnihand_o10_model.contract import (
    ACTIVE_JOINT_BASES,
    FULL_JOINT_BASES,
    PASSIVE_JOINT_BASES,
    SIDE_PREFIX,
    expected_couplings,
    expected_polycoef,
    joint_name,
    link_name,
    palm_frame,
    side_contract,
)


def _xml_to_string(elem: ET.Element) -> str:
    return ET.tostring(elem, encoding="unicode")


def build_urdf(
    side: str,
    *,
    joint_order: Optional[Sequence[str]] = None,
    drop_joint: Optional[str] = None,
    extra_joint: Optional[str] = None,
    bad_limit_for: Optional[str] = None,
    bad_limit_value: Optional[Tuple[str, str]] = None,
    missing_link: Optional[str] = None,
    joint_type_override: Optional[dict] = None,
    include_mimic: bool = True,
) -> str:
    """Build a synthetic URDF for ``side``.

    Mutation kwargs produce *invalid* documents for negative tests:

    * ``joint_order``: override the joint sequence (e.g. reordered or truncated);
    * ``drop_joint``: remove a base joint by name;
    * ``extra_joint``: add a spurious movable joint;
    * ``bad_limit_for`` / ``bad_limit_value``: set wrong (lower, upper) on a joint;
    * ``missing_link``: omit a required link;
    * ``joint_type_override``: map joint base -> a wrong type (e.g. ``continuous``).
    """
    contract = side_contract(side)
    if joint_order is None:
        bases = list(FULL_JOINT_BASES)
    else:
        bases = list(joint_order)
    if drop_joint is not None:
        bases = [b for b in bases if b != drop_joint]

    root = ET.Element("robot", {"name": f"omnihand_{side}"})

    present_links = set()
    # Root link.
    present_links.add("base_link")
    ET.SubElement(root, "link", {"name": "base_link"})
    # Palm frame.
    present_links.add(palm_frame(side))
    ET.SubElement(root, "link", {"name": palm_frame(side)})

    # Passive joint limits are not part of the pinned active contract; give them
    # a plausible finite range so the document is well-formed.
    passive_limit = ("0.0", "1.7540558982543013")

    limits_by_base = {base: contract.active_limits[i]
                      for i, base in enumerate(ACTIVE_JOINT_BASES)}

    for base in bases:
        jname = joint_name(side, base)
        jtype = "revolute"
        if joint_type_override and base in joint_type_override:
            jtype = joint_type_override[base]
        parent = link_name(side, base) if base != ACTIVE_JOINT_BASES[0] else palm_frame(side)
        present_links.add(parent)
        child = link_name(side, base)
        present_links.add(child)
        ET.SubElement(root, "link", {"name": parent})
        ET.SubElement(root, "link", {"name": child})

        if base in limits_by_base:
            low, high = limits_by_base[base]
            low_s, high_s = f"{low}", f"{high}"
        else:
            low_s, high_s = passive_limit
        if bad_limit_for == base and bad_limit_value is not None:
            low_s, high_s = bad_limit_value

        joint_elem = ET.SubElement(
            root, "joint", {"name": jname, "type": jtype}
        )
        ET.SubElement(joint_elem, "parent", {"link": parent})
        ET.SubElement(joint_elem, "child", {"link": child})
        ET.SubElement(
            joint_elem, "limit",
            {"lower": low_s, "upper": high_s, "effort": "1.0", "velocity": "1.0"},
        )
        if include_mimic and base in PASSIVE_JOINT_BASES:
            driver = next(
                spec.active for spec in expected_couplings(side)
                if spec.passive == base
            )
            ET.SubElement(
                joint_elem, "mimic",
                {"joint": joint_name(side, driver), "multiplier": "0.5", "offset": "0"},
            )

    # Required tip links (frames).
    for tip_base in ("thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip"):
        if missing_link == tip_base:
            continue
        tip = f"{SIDE_PREFIX[side]}{tip_base}"
        present_links.add(tip)
        ET.SubElement(root, "link", {"name": tip})

    if missing_link == "palm":
        for palm_elem in root.findall(f"link[@name='{palm_frame(side)}']"):
            root.remove(palm_elem)
    if missing_link == "root":
        for root_elem in root.findall("link[@name='base_link']"):
            root.remove(root_elem)

    if extra_joint is not None:
        ej = ET.SubElement(root, "joint", {"name": extra_joint, "type": "revolute"})
        ET.SubElement(ej, "parent", {"link": "base_link"})
        ET.SubElement(ej, "child", {"link": "extra_link"})
        ET.SubElement(ej, "limit", {"lower": "0", "upper": "1", "effort": "1", "velocity": "1"})
        ET.SubElement(root, "link", {"name": "extra_link"})

    return _xml_to_string(root)


def build_mjcf(
    side: str,
    *,
    coupling_override: Optional[Iterable] = None,
    drop_coupling: Optional[str] = None,
    extra_coupling: Optional[dict] = None,
    polycoef_count_for: Optional[str] = None,
    polycoef_count: int = 4,
    bad_polycoef_for: Optional[str] = None,
    bad_polycoef: Optional[Sequence[float]] = None,
    duplicate_coupling: bool = False,
) -> str:
    """Build a synthetic MJCF for ``side``.

    Each coupling is emitted as ``<equality><joint joint1=passive joint2=active
    polycoef="c0 c1 c2 c3 c4"/></equality>`` to match the upstream orientation.
    Mutation kwargs produce invalid documents for negative tests.
    """
    root = ET.Element("mujoco", {"model": f"omnihand_{side}"})
    ET.SubElement(root, "compiler", {"angle": "radian"})
    worldbody = ET.SubElement(root, "worldbody")
    palm = ET.SubElement(worldbody, "body", {"name": palm_frame(side)})
    ET.SubElement(palm, "geom", {"type": "sphere", "size": "0.001"})

    equality = ET.SubElement(root, "equality")

    specs = list(expected_couplings(side))
    if coupling_override is not None:
        specs = list(coupling_override)
    if drop_coupling is not None:
        specs = [s for s in specs if s.passive != drop_coupling]

    emitted = []
    for spec in specs:
        passive = joint_name(side, spec.passive)
        active = joint_name(side, spec.active)
        coef = spec.polycoef
        if bad_polycoef_for == spec.passive and bad_polycoef is not None:
            coef = tuple(bad_polycoef)
        if polycoef_count_for == spec.passive:
            coef = tuple(coef[:polycoef_count]) if polycoef_count < 5 else tuple(coef)
        coef_str = " ".join(repr(c) for c in coef)
        ET.SubElement(equality, "joint", {
            "joint1": passive, "joint2": active, "polycoef": coef_str,
        })
        emitted.append((spec.passive, spec.active))

    if duplicate_coupling and specs:
        spec = specs[0]
        passive = joint_name(side, spec.passive)
        active = joint_name(side, spec.active)
        coef_str = " ".join(repr(c) for c in spec.polycoef)
        ET.SubElement(equality, "joint", {
            "joint1": passive, "joint2": active, "polycoef": coef_str,
        })

    if extra_coupling is not None:
        ET.SubElement(equality, "joint", {
            "joint1": extra_coupling["joint1"],
            "joint2": extra_coupling["joint2"],
            "polycoef": extra_coupling.get("polycoef", "0 1 0 0 0"),
        })

    return _xml_to_string(root)


def build_mjcf_with_thumb_dip_coef(side: str, coef: Sequence[float]) -> str:
    """Build a synthetic MJCF overriding only the thumb_dip polycoef."""
    override = []
    for spec in expected_couplings(side):
        if spec.passive == "thumb_dip":
            from omnihand_o10_model.contract import CouplingSpec
            override.append(CouplingSpec(
                passive=spec.passive, active=spec.active,
                polycoef=tuple(coef), side_asymmetric=spec.side_asymmetric,
            ))
        else:
            override.append(spec)
    return build_mjcf(side, coupling_override=override)
