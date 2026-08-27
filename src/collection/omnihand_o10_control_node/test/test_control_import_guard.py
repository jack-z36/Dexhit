"""Purity guard: control Application/core/contracts MUST NOT import rclpy/ROS.

ARCHITECTURE A03 forbids the Application (and the pure core/contracts layers it
sits on) from importing rclpy, ROS messages or vendor code.  Only the ``node``
and ``adapters`` layers may touch the ROS runtime.  This test enforces the split
at the source (AST scan) and at runtime (sys.modules).
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PURE_DIRS = (
    PACKAGE_ROOT / "omnihand_o10_control" / "contracts.py",
    PACKAGE_ROOT / "omnihand_o10_control" / "core",
    PACKAGE_ROOT / "omnihand_o10_control" / "application",
)

# Must never be imported by contracts / core / application.
FORBIDDEN_TOP_LEVEL = {
    "rclpy",
    "sensor_msgs",
    "std_msgs",
    "geometry_msgs",
    "builtin_interfaces",
    "action_msgs",
    "rokoko_omnihand_msgs",
    "omnihand_node",
    "omnihand_2025",
    "rokoko_omnihand_system_test",
}

ALLOWED_THIRD_PARTY = {"numpy"}


def _pure_python_files():
    files = [PACKAGE_ROOT / "omnihand_o10_control" / "contracts.py"]
    for directory in PURE_DIRS[1:]:
        if directory.is_dir():
            files.extend(sorted(directory.glob("*.py")))
    return files


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
    def test_no_forbidden_imports_in_pure_layers(self):
        offenders: list[str] = []
        for path in _pure_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            bad = _imported_top_level_names(tree) & FORBIDDEN_TOP_LEVEL
            if bad:
                offenders.append(f"{path.name}: {sorted(bad)}")
        assert not offenders, "forbidden imports found: " + "; ".join(offenders)

    def test_only_allowed_third_party_imports_in_pure_layers(self):
        own_prefix = "omnihand_o10_control"
        for path in _pure_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            external = {
                n
                for n in _imported_top_level_names(tree)
                if not n.startswith(own_prefix)
                and not n.startswith("omnihand_o10_contracts")
                and n not in sys.stdlib_module_names
            }
            unexpected = external - ALLOWED_THIRD_PARTY
            assert not unexpected, (
                f"{path.name} imports unexpected third-party: {sorted(unexpected)}"
            )


class TestRuntimePurity:
    def test_importing_pure_layers_does_not_pull_ros(self):
        removed: dict[str, object] = {}
        for mod in list(sys.modules):
            top = mod.split(".")[0]
            if top in FORBIDDEN_TOP_LEVEL:
                removed[mod] = sys.modules[mod]
                del sys.modules[mod]
        try:
            importlib.import_module("omnihand_o10_control.contracts")
            importlib.import_module("omnihand_o10_control.core.slew_limiter")
            importlib.import_module("omnihand_o10_control.core.soft_target")
            importlib.import_module("omnihand_o10_control.application.control_session")

            present = {
                top
                for mod in sys.modules
                for top in (mod.split(".")[0],)
                if top in FORBIDDEN_TOP_LEVEL
            }
            assert not present, (
                "importing the pure layers pulled forbidden modules: "
                + str(sorted(present))
            )
        finally:
            # Restore the removed modules so later tests in this process keep
            # a single, consistent rclpy/ROS runtime.
            sys.modules.update(removed)