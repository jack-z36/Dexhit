"""Purity guard: omnihand_o10_contracts MUST stay a pure types layer.

It MUST NOT import rclpy, ROS messages, Pinocchio, NLopt, vendor code or test
code (ARCHITECTURE Types/Contracts row; invariants A11/A13/A17). numpy and the
Python standard library are the only allowed dependencies. This test enforces
the contract both at the source (AST scan) and at runtime (sys.modules).
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PACKAGE_ROOT / "omnihand_o10_contracts"

# Modules that must never be imported by this package. `rclpy` and ROS message
# packages tie the code to the ROS runtime; pinocchio/nlopt are numeric backends
# confined to retargeting adapters; omnihand_node is the vendor surface.
FORBIDDEN_TOP_LEVEL = {
    "rclpy",
    "sensor_msgs",
    "std_msgs",
    "geometry_msgs",
    "builtin_interfaces",
    "action_msgs",
    "pinocchio",
    "nlopt",
    "omnihand_node",
    "omnihand_2025",
}

ALLOWED_THIRD_PARTY = {"numpy"}


def _source_python_files():
    return sorted(SOURCE_DIR.glob("*.py"))


def _imported_top_level_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


class TestSourcePurity:
    def test_source_directory_exists_and_contains_python(self):
        files = _source_python_files()
        assert files, f"no python source under {SOURCE_DIR}"

    def test_no_forbidden_imports_in_source(self):
        offenders: list[str] = []
        for path in _source_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            bad = _imported_top_level_names(tree) & FORBIDDEN_TOP_LEVEL
            if bad:
                offenders.append(f"{path.name}: {sorted(bad)}")
        assert not offenders, "forbidden imports found: " + "; ".join(offenders)

    def test_only_allowed_third_party_imports(self):
        own_name = "omnihand_o10_contracts"
        for path in _source_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            external = {
                n for n in _imported_top_level_names(tree)
                if not n.startswith(own_name) and n not in sys.stdlib_module_names
            }
            unexpected = external - ALLOWED_THIRD_PARTY
            assert not unexpected, (
                f"{path.name} imports unexpected third-party: {sorted(unexpected)}"
            )


class TestRuntimePurity:
    def test_importing_package_does_not_pull_ros_or_numeric_backends(self):
        # Drop any previously imported forbidden modules so the check measures
        # exactly what this package pulls in.
        for mod in list(sys.modules):
            top = mod.split(".")[0]
            if top in FORBIDDEN_TOP_LEVEL:
                del sys.modules[mod]
        importlib.import_module("omnihand_o10_contracts")
        # Also import every submodule so conditional imports cannot hide.
        for path in _source_python_files():
            stem = path.stem
            if stem == "__init__":
                continue
            importlib.import_module(f"omnihand_o10_contracts.{stem}")

        present = {
            top for mod in sys.modules
            for top in (mod.split(".")[0],)
            if top in FORBIDDEN_TOP_LEVEL
        }
        assert not present, (
            "importing the package pulled forbidden modules: " + str(sorted(present))
        )

    def test_package_exposes_public_contract_surface(self):
        import omnihand_o10_contracts as c

        for name in (
            "Side",
            "ACTIVE_JOINT_COUNT",
            "ACTIVE_JOINT_NAMES",
            "ACTIVE_JOINT_INDEX",
            "JOINT_LIMITS",
            "JointLimits",
            "JointTarget",
            "JointFeedback",
            "JointError",
            "JointSampleTime",
        ):
            assert hasattr(c, name), f"missing public symbol: {name}"
