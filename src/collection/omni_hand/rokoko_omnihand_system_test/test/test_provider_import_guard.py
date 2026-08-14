"""Vendor-free guard: the software provider MUST NOT use the vendor package.

ARCHITECTURE A04 forbids any dependency on the vendor ``omnihand_node``
package; the software provider (A09) emulates the wire contract instead.  The
provider IS a ROS node, so rclpy and the standard ROS message packages are
expected; only the vendor adapter and numeric backends are forbidden.
"""

import ast
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PACKAGE_ROOT / "rokoko_omnihand_system_test"

FORBIDDEN_TOP_LEVEL = {
    "omnihand_node",
    "omnihand_2025",
    "pinocchio",
    "nlopt",
    "rokoko_hand_receiver",
}

ALLOWED_THIRD_PARTY = {
    "rclpy",
    "sensor_msgs",
    "std_msgs",
    "geometry_msgs",
    "builtin_interfaces",
    "action_msgs",
}


def _source_python_files():
    # This guard protects only the Provider.  The T10 graph harness is expected
    # to import the three real business nodes, while the Provider itself must
    # remain vendor-free and backend-free.
    return [SOURCE_DIR / "provider.py"]


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


def test_no_forbidden_imports_in_provider_source():
    offenders: list[str] = []
    for path in _source_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _imported_top_level_names(tree) & FORBIDDEN_TOP_LEVEL
        if bad:
            offenders.append(f"{path.name}: {sorted(bad)}")
    assert not offenders, "forbidden imports found: " + "; ".join(offenders)


def test_no_unexpected_third_party_imports():
    own_name = "rokoko_omnihand_system_test"
    for path in _source_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        external = {
            n
            for n in _imported_top_level_names(tree)
            if not n.startswith(own_name)
            and not n.startswith("omnihand_o10_contracts")
            and not n.startswith("rokoko_omnihand_msgs")
            and n not in sys.stdlib_module_names
        }
        unexpected = external - ALLOWED_THIRD_PARTY
        assert not unexpected, (
            f"{path.name} imports unexpected third-party: {sorted(unexpected)}"
        )
