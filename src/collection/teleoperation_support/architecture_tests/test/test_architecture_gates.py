"""Executable A01-A13/A15-A20/A22-A27 architecture gates.

Each test emits the concrete package, path, or import edge that violated the
invariant.  The test package is deliberately source-oriented: it is a blocking
gate over the current checkout and is never imported by production packages.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import re
import xml.etree.ElementTree as ET


COLLECTION = Path(__file__).resolve().parents[3]
WORKSPACE = COLLECTION.parents[1]
SUPPORT = COLLECTION / "teleoperation_support"
THIRD_PARTY = COLLECTION / "third_party"
PACKAGE_ROOTS = {
    "rokoko_hand_receiver": COLLECTION / "rokoko_hand_receiver_node",
    "hand_retargeting": COLLECTION / "hand_retargeting_node",
    "omnihand_o10_control": COLLECTION / "omnihand_o10_control_node",
    "omnihand_o10_hardware_adapter": (
        COLLECTION / "omnihand_o10_hardware_provider_node"
    ),
    "rokoko_omnihand_launchpad": COLLECTION / "rokoko_omnihand_launchpad_node",
    "rokoko_omnihand_msgs": SUPPORT / "ros_interfaces",
    "omnihand_o10_contracts": SUPPORT / "o10_contracts",
    "omnihand_o10_model": SUPPORT / "o10_model_assets",
    "rokoko_omnihand_bringup": SUPPORT / "production_bringup",
    "rokoko_omnihand_system_test": SUPPORT / "system_tests",
    "rokoko_omnihand_architecture_test": SUPPORT / "architecture_tests",
}
MANAGED = {
    "rokoko_omnihand_msgs",
    "omnihand_o10_contracts",
    "omnihand_o10_model",
    "rokoko_hand_receiver",
    "hand_retargeting",
    "omnihand_o10_control",
    "omnihand_o10_hardware_adapter",
    "rokoko_omnihand_bringup",
    "rokoko_omnihand_system_test",
    "rokoko_omnihand_architecture_test",
    "rokoko_omnihand_launchpad",
}
PRODUCTION = MANAGED - {
    "rokoko_omnihand_system_test",
    "rokoko_omnihand_architecture_test",
}
RUNTIME_PYTHON = {
    "rokoko_hand_receiver",
    "hand_retargeting",
    "omnihand_o10_control",
    "omnihand_o10_hardware_adapter",
    "rokoko_omnihand_bringup",
    "rokoko_omnihand_system_test",
    "rokoko_omnihand_architecture_test",
    "rokoko_omnihand_launchpad",
}

# Launchpad is a production package at the dependency-graph level, but these
# two explicitly named adapters are the only allowed mock/sim seams.  Keep
# the exception narrow: a new Launchpad module must opt into this list rather
# than inheriting permission to load the software Provider.
LAUNCHPAD_MOCK_ADAPTERS = frozenset({
    "synthetic_input.py",
    "sim_provider.py",
})


def _package_root(package: str) -> Path:
    return PACKAGE_ROOTS[package]


def _manifest(package: str) -> ET.Element:
    return ET.parse(_package_root(package) / "package.xml").getroot()


def _deps(package: str, include_tests: bool = False) -> set[str]:
    root = _manifest(package)
    tags = {"depend", "build_depend", "build_export_depend", "exec_depend"}
    if include_tests:
        tags.add("test_depend")
    return {
        element.text.strip()
        for element in root
        if element.tag in tags and element.text and element.text.strip() in MANAGED
    }


def _python_files(package: str, *, include_tests: bool = False) -> list[Path]:
    root = _package_root(package)
    files = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if not include_tests and "test" in path.parts:
            continue
        if "jazzy" in path.parts:
            continue
        files.append(path)
    return files


def _is_launchpad_mock_adapter(path: Path) -> bool:
    return (
        path.parent.name == "rokoko_omnihand_launchpad"
        and path.name in LAUNCHPAD_MOCK_ADAPTERS
    )


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append((node.module, node.lineno))
    return result


def _managed_imports(package: str) -> list[tuple[Path, str, int]]:
    result = []
    for path in _python_files(package):
        for module, line in _imports(path):
            root = module.split(".", 1)[0]
            if root in MANAGED:
                result.append((path, root, line))
    return result


def _assert_no_edges(edges: list[tuple[Path, str, int]], forbidden: set[str]) -> None:
    violations = [
        f"{path}:{line}: imports forbidden package {target}"
        for path, target, line in edges
        if target in forbidden
    ]
    assert not violations, "\n".join(violations)


def test_A01_package_dependency_graph_is_acyclic_and_allowed():
    allowed = {
        "rokoko_omnihand_msgs": set(),
        "omnihand_o10_contracts": set(),
        "omnihand_o10_model": {"omnihand_o10_contracts"},
        "rokoko_hand_receiver": {"rokoko_omnihand_msgs"},
        "hand_retargeting": {
            "rokoko_omnihand_msgs", "omnihand_o10_contracts", "omnihand_o10_model"
        },
        "omnihand_o10_control": {"rokoko_omnihand_msgs", "omnihand_o10_contracts"},
        "omnihand_o10_hardware_adapter": {
            "rokoko_omnihand_msgs", "omnihand_o10_contracts"
        },
        "rokoko_omnihand_bringup": {
            "rokoko_hand_receiver", "hand_retargeting", "omnihand_o10_control",
            "omnihand_o10_hardware_adapter", "rokoko_omnihand_msgs",
            "omnihand_o10_model",
        },
        "rokoko_omnihand_system_test": {
            "rokoko_hand_receiver", "hand_retargeting", "omnihand_o10_control",
            "rokoko_omnihand_msgs", "omnihand_o10_contracts", "omnihand_o10_model",
        },
        "rokoko_omnihand_architecture_test": set(),
        "rokoko_omnihand_launchpad": set(),
    }
    violations = []
    graph = {}
    for package in MANAGED:
        graph[package] = _deps(package)
        for target in graph[package]:
            if target not in allowed[package]:
                violations.append(f"manifest edge {package} -> {target}")
    visited: set[str] = set()
    active: set[str] = set()

    def visit(package: str, trail: tuple[str, ...] = ()):
        if package in active:
            violations.append("dependency cycle: " + " -> ".join(trail + (package,)))
            return
        if package in visited:
            return
        active.add(package)
        for target in graph[package]:
            visit(target, trail + (package,))
        active.remove(package)
        visited.add(package)

    for package in MANAGED:
        visit(package)
    assert not violations, "\n".join(violations)


def test_A02_core_import_boundaries():
    banned = {
        "rclpy", "rcl_interfaces", "launch", "launch_ros", "ament_index_python",
        "rokoko_omnihand_msgs", "sensor_msgs", "std_msgs", "builtin_interfaces",
        "socket", "urllib", "requests", "omnihand_node",
    }
    violations = []
    for package in RUNTIME_PYTHON:
        for path in _python_files(package):
            if "core" not in path.parts:
                continue
            for module, line in _imports(path):
                if module.split(".", 1)[0] in banned:
                    violations.append(f"{path}:{line}: core imports {module}")
    assert not violations, "\n".join(violations)


def test_A03_application_import_boundaries():
    banned = {
        "rclpy", "rcl_interfaces", "launch", "launch_ros", "ament_index_python",
        "rokoko_omnihand_msgs", "sensor_msgs", "std_msgs", "builtin_interfaces",
        "omnihand_node", "omnihand_o10_hardware_adapter",
        "rokoko_omnihand_system_test",
    }
    violations = []
    for package in RUNTIME_PYTHON:
        for path in _python_files(package):
            if "application" not in path.parts:
                continue
            for module, line in _imports(path):
                root = module.split(".", 1)[0]
                if root in banned or root in {"adapters", "node"}:
                    violations.append(f"{path}:{line}: application imports {module}")
    assert not violations, "\n".join(violations)


def test_A04_control_has_no_vendor_dependency():
    forbidden = {"omnihand_node", "omnihand_o10_hardware_adapter", "can", "usb"}
    manifest = " ".join(sorted(_deps("omnihand_o10_control", include_tests=True)))
    assert not any(word in manifest.lower() for word in forbidden)
    _assert_no_edges(_managed_imports("omnihand_o10_control"), forbidden)


def test_A05_receiver_stops_at_raw_boundary():
    forbidden = {"omnihand_o10_contracts", "omnihand_o10_model", "hand_retargeting", "omnihand_o10_control"}
    assert not (_deps("rokoko_hand_receiver") & forbidden)
    _assert_no_edges(_managed_imports("rokoko_hand_receiver"), forbidden)


def test_A06_retarget_and_control_are_decoupled():
    assert "omnihand_o10_control" not in _deps("hand_retargeting")
    assert "hand_retargeting" not in _deps("omnihand_o10_control")
    _assert_no_edges(_managed_imports("hand_retargeting"), {"omnihand_o10_control"})
    _assert_no_edges(_managed_imports("omnihand_o10_control"), {"hand_retargeting"})


def test_A07_control_does_not_consume_retargeting_state():
    violations = []
    for path in _python_files("omnihand_o10_control"):
        text = path.read_text(encoding="utf-8")
        if "RetargetingState" in text or "/hand_retargeting/" in text:
            violations.append(str(path))
    assert not violations, "control source mentions retargeting state: " + ", ".join(violations)


def test_A08_production_excludes_test_provider():
    violations = []
    for package in PRODUCTION:
        if "rokoko_omnihand_system_test" in _deps(package, include_tests=True):
            violations.append(f"manifest {package} -> rokoko_omnihand_system_test")
        for path in _python_files(package):
            if package == "rokoko_omnihand_launchpad" and _is_launchpad_mock_adapter(path):
                continue
            text = path.read_text(encoding="utf-8")
            imported = {
                module.split(".", 1)[0]
                for module, _line in _imports(path)
            }
            if "rokoko_omnihand_system_test" in imported or "SoftwareO10Provider" in text:
                violations.append(str(path))
    assert not violations, "production includes test Provider: " + ", ".join(violations)


def test_A09_software_provider_has_no_vendor_surface():
    forbidden = {"omnihand_node", "omnihand_o10_hardware_adapter", "can", "usb", "serial", "ctypes"}
    _assert_no_edges(_managed_imports("rokoko_omnihand_system_test"), forbidden)
    declared = _deps("rokoko_omnihand_system_test", include_tests=True)
    assert not declared & {"omnihand_o10_hardware_adapter", "omnihand_node"}
    binaries = [
        path for path in _package_root("rokoko_omnihand_system_test").rglob("*")
        if path.suffix in {".so", ".dll", ".dylib"}
    ]
    assert not binaries, "software Provider contains binary surface: " + ", ".join(map(str, binaries))


def test_A10_hardware_port_contract_is_present_on_both_sides():
    hardware = _package_root("omnihand_o10_hardware_adapter")
    provider = _package_root("rokoko_omnihand_system_test")
    hardware_text = "\n".join(path.read_text(encoding="utf-8") for path in _python_files("omnihand_o10_hardware_adapter", include_tests=True))
    provider_text = "\n".join(path.read_text(encoding="utf-8") for path in _python_files("rokoko_omnihand_system_test", include_tests=True))
    for operation in ("send_command", "read_feedback", "query_errors", "read_active_joints"):
        assert operation in hardware_text, f"hardware contract missing {operation}"
    for wire_operation in (
        "joint_cmd", "joint_states", "joint_error_cmd", "read_active_joints"
    ):
        assert wire_operation in provider_text, (
            f"software Provider wire contract missing {wire_operation}"
        )
    assert any(path.name.startswith("test_") for path in hardware.joinpath("test").glob("*.py"))


def test_A11_active_joint_contract_has_one_code_owner():
    owners = []
    allowed = _package_root("omnihand_o10_contracts") / "omnihand_o10_contracts" / "joints.py"
    names = {"ACTIVE_JOINT_NAMES", "ACTIVE_JOINT_INDEX", "JOINT_LIMITS", "_RIGHT_LIMITS", "_LEFT_LIMITS"}
    for package in MANAGED:
        for path in _python_files(package):
            if path == allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in names:
                            # The model package may expose a derived tuple
                            # view for its structural API, but it may not
                            # define a second numeric source of truth.
                            if target.id in {"_RIGHT_LIMITS", "_LEFT_LIMITS"}:
                                if any(
                                    isinstance(child, ast.Name)
                                    and child.id == "JOINT_LIMITS"
                                    for child in ast.walk(node.value)
                                ):
                                    continue
                            owners.append(f"{path}:{node.lineno}: {target.id}")
    assert not owners, "duplicate active-joint owner(s):\n" + "\n".join(owners)


def test_A12_model_assets_use_install_or_external_fixture_boundary():
    forbidden = re.compile(r"/(?:home|workspace|tmp)/[^\"']*omnihand", re.IGNORECASE)
    violations = []
    for path in _python_files("omnihand_o10_model", include_tests=False):
        text = path.read_text(encoding="utf-8")
        if forbidden.search(text):
            violations.append(str(path))
    loader = (_package_root("omnihand_o10_model") / "omnihand_o10_model/loader.py").read_text(encoding="utf-8")
    assert "get_package_share_directory" in loader
    assert "OMNIHAND_O10_MODEL_FIXTURE" in loader
    assert not violations, "hard-coded model asset path(s): " + ", ".join(violations)


def test_A13_numeric_backends_are_adapters():
    violations = []
    for path in _python_files("hand_retargeting"):
        for module, line in _imports(path):
            if module.split(".", 1)[0].lower() in {"pinocchio", "nlopt"}:
                if "adapters" not in path.parts and path.name != "node.py":
                    violations.append(f"{path}:{line}: {module}")
    assert not violations, "numeric backend leaked outside adapter/composition: " + ", ".join(violations)


def test_A15_retarg_side_aggregates_are_isolated():
    import sys

    sys.path.insert(0, str(_package_root("hand_retargeting")))
    sys.path.insert(0, str(_package_root("omnihand_o10_contracts")))
    sys.path.insert(0, str(_package_root("omnihand_o10_model")))
    from hand_retargeting.application.session import RetargetingSession
    from hand_retargeting.contracts import RetargetingConfig
    from hand_retargeting.core.normalization import RobotHandGeometry
    from omnihand_o10_contracts import Side

    config = RetargetingConfig(
        palm_y_epsilon=1e-6, palm_x_epsilon=1e-6, finger_length_epsilon=1e-6,
        length_window_size=2, stable_window_count=1,
        length_nmad_thresholds=(0.1,) * 5,
        frozen_length_relative_thresholds=(0.1,) * 5,
        ik_residual_thresholds=(0.1,) * 5, ik_max_evaluations=1,
        ik_max_time_sec=0.01, smooth_time_constants=(0.1,) * 10,
        stale_timeout_sec=1.0, recovery_min_valid_frames=1,
        recovery_min_duration_sec=0.1, recovery_confirmation_timeout_sec=0.5,
    )
    geometry = RobotHandGeometry(
        tuple((float(index), 0.0, 0.0) for index in range(5)),
        (1.0,) * 5,
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )
    left = RetargetingSession(Side.LEFT, config, geometry)
    right = RetargetingSession(Side.RIGHT, config, geometry)
    assert left._filter is not right._filter
    assert left._last_valid is not right._last_valid


def test_A16_wire_enums_are_owned_by_interface_package():
    interface_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _package_root("rokoko_omnihand_msgs").rglob("*")
        if path.suffix in {".msg", ".srv"}
    )
    assert "PHASE_FAULT_LATCHED=5" in interface_text
    assert "ARM_REJECTED_TARGET_STALE=14" in interface_text
    assert "READ_SUCCESS=0" in interface_text
    literal = re.compile(r"\b(?:PHASE|EVENT|ARM|DISARM|CLEAR_FAULT|READ)_[A-Z0-9_]+\s*=\s*\d+")
    violations = []
    for package in PRODUCTION | {"rokoko_omnihand_system_test"}:
        for path in _python_files(package):
            if literal.search(path.read_text(encoding="utf-8")):
                violations.append(str(path))
    assert not violations, "wire numeric enum copied by consumer: " + ", ".join(violations)


def test_A17_no_utils_or_common_dependency_dumping_ground():
    violations = []
    for package in MANAGED - {"rokoko_omnihand_architecture_test"}:
        root = _package_root(package)
        for name in ("utils", "common"):
            if (root / name).exists():
                violations.append(str(root / name))
        for path in _python_files(package, include_tests=True):
            for module, line in _imports(path):
                if module.split(".", 1)[0] in {"utils", "common"}:
                    violations.append(f"{path}:{line}: {module}")
    assert not violations, "shared dumping ground found:\n" + "\n".join(violations)


def test_A18_experimental_parameters_are_required():
    from inspect import signature
    import sys

    sys.path.insert(0, str(_package_root("hand_retargeting")))
    sys.path.insert(0, str(_package_root("omnihand_o10_control")))
    sys.path.insert(0, str(_package_root("omnihand_o10_contracts")))
    from hand_retargeting.contracts import RetargetingConfig
    from omnihand_o10_control.contracts import ControlConfig

    assert all(parameter.default is parameter.empty for parameter in signature(RetargetingConfig).parameters.values())
    assert all(parameter.default is parameter.empty for parameter in signature(ControlConfig).parameters.values())
    control_node = (_package_root("omnihand_o10_control") / "omnihand_o10_control/node.py").read_text(encoding="utf-8")
    retarget_node = (_package_root("hand_retargeting") / "hand_retargeting/node.py").read_text(encoding="utf-8")
    assert "required O10 control parameter is missing" in control_node
    assert "required experimental parameters are missing" in retarget_node
    launch = (_package_root("rokoko_omnihand_bringup") / "launch/production.launch.py").read_text(encoding="utf-8")
    assert "default_value" not in launch


def test_A19_vendor_prefix_is_external_install_artifact():
    vendor = THIRD_PARTY / "agillink_omnihand_sdk/linux/x64/ros2/jazzy"
    assert (THIRD_PARTY / "COLCON_IGNORE").is_file()
    assert (vendor / "COLCON_IGNORE").is_file()
    violations = []
    for package in MANAGED - {"rokoko_omnihand_architecture_test"}:
        for path in _python_files(package, include_tests=True):
            text = path.read_text(encoding="utf-8")
            if (
                "src/collection/omni_hand/jazzy" in text
                or "third_party/agillink_omnihand_sdk" in text
                or "/jazzy/lib/" in text
            ):
                violations.append(str(path))
    assert not violations, "managed source owns vendor prefix: " + ", ".join(violations)


def test_A20_production_business_node_inventory():
    launch = (_package_root("rokoko_omnihand_bringup") / "launch/production.launch.py").read_text(encoding="utf-8")
    allowed = {
        "rokoko_hand_receiver", "hand_retargeting", "omnihand_o10_control",
        "omnihand_o10_hardware_adapter",
    }
    packages = set(re.findall(r'package="([^"]+)"', launch))
    assert packages == allowed, f"unexpected production package inventory: {sorted(packages)}"
    assert "system_test" not in launch
    assert "SoftwareO10Provider" not in launch


def test_A22_owned_runtime_packages_use_ament_python():
    violations = []
    for package in RUNTIME_PYTHON:
        root = _manifest(package)
        build_types = [
            child.text.strip()
            for child in root.findall("./export/build_type")
            if child.text
        ]
        if build_types != ["ament_python"]:
            violations.append(f"{package}: {build_types}")
    assert not violations, "owned runtime language policy violation: " + ", ".join(violations)


def test_A23_launchpad_skeleton_boundary():
    root = _package_root("rokoko_omnihand_launchpad")
    assert root == COLLECTION / "rokoko_omnihand_launchpad_node"
    assert (root / "package.xml").is_file()
    assert (root / "resource/rokoko_omnihand_launchpad").is_file()
    assert (root / "web/package.json").is_file()
    assert (root / "web/src/App.vue").is_file()

    main = (root / "rokoko_omnihand_launchpad/main.py").read_text(encoding="utf-8")
    app = (root / "rokoko_omnihand_launchpad/app.py").read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in main
    assert "PORT = 8710" in main
    assert "uvicorn.run" in main
    assert "FastAPI" in app
    assert "业务节点尚未接入" in app

    assert not _deps("rokoko_omnihand_launchpad")
    # The manifest must remain independent of all managed ROS/business
    # packages.  Mock/sim adapters are the sole intentional source-level
    # exception and are checked separately by A08.
    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _python_files("rokoko_omnihand_launchpad", include_tests=False)
        if not _is_launchpad_mock_adapter(path)
    )
    assert "rokoko_omnihand_system_test" not in production_source

    orchestrator = (root / "rokoko_omnihand_launchpad/orchestrator.py").read_text(
        encoding="utf-8"
    )
    assert "execution_mode == \"real\"" in orchestrator
    assert "_contains_system_test(profile_data)" in orchestrator


def test_A25_collection_top_level_is_production_node_first():
    expected = {
        "rokoko_hand_receiver_node",
        "hand_retargeting_node",
        "omnihand_o10_control_node",
        "omnihand_o10_hardware_provider_node",
        "rokoko_omnihand_launchpad_node",
        "teleoperation_support",
        "third_party",
    }
    actual = {
        path.name
        for path in COLLECTION.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert actual == expected, f"unexpected Collection top-level directories: {sorted(actual)}"
    assert not (COLLECTION / "omni_hand").exists()

    support_expected = {
        "ros_interfaces",
        "o10_contracts",
        "o10_model_assets",
        "production_bringup",
        "system_tests",
        "architecture_tests",
    }
    support_actual = {
        path.name
        for path in SUPPORT.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert support_actual == support_expected
    assert not (SUPPORT / "package.xml").exists()

    for package, root in PACKAGE_ROOTS.items():
        names = [
            element.text.strip()
            for element in ET.parse(root / "package.xml").getroot().findall("name")
            if element.text
        ]
        assert names == [package], f"{root} owns unexpected package name(s): {names}"


def test_A26_node_directory_and_support_executable_roles():
    expected_executables = {
        "rokoko_hand_receiver": "rokoko_hand_receiver_node",
        "hand_retargeting": "hand_retargeting_node",
        "omnihand_o10_control": "o10_control_node",
        "omnihand_o10_hardware_adapter": "omnihand_o10_hardware_provider",
        "rokoko_omnihand_launchpad": "rokoko_omnihand_launchpad",
    }
    for package, executable in expected_executables.items():
        setup_text = (_package_root(package) / "setup.py").read_text(encoding="utf-8")
        assert executable in setup_text, f"{package} does not expose {executable}"

    support_setup_text = "\n".join(
        path.read_text(encoding="utf-8") for path in SUPPORT.glob("*/setup.py")
    )
    assert "software_o10_provider" in support_setup_text
    for executable in expected_executables.values():
        assert executable not in support_setup_text


def test_A27_root_operator_scripts_keep_canonical_interfaces():
    expected = {
        "init_omnihand.sh": "src/collection",
        "start_omnihand_control.sh": (
            "teleoperation_support/production_bringup/scripts/"
            "start_omnihand_control.sh"
        ),
        "start_launchpad.sh": "rokoko_omnihand_launchpad_node",
        "clear_o10_fault.sh": "[left|right|both]",
        "decode_rokoko_udp.sh": "[--port PORT] [--count N]",
    }
    for name, marker in expected.items():
        path = WORKSPACE / name
        assert path.is_file(), f"missing root operator entry: {path}"
        assert path.stat().st_mode & 0o111, f"root operator entry is not executable: {path}"
        text = path.read_text(encoding="utf-8")
        assert marker in text, f"{name} lost command/path contract marker: {marker}"
        if name == "init_omnihand.sh":
            # The new init detects and removes generated caches that still
            # point at the deleted pre-migration source root.
            assert text.count("/src/collection/omni_hand/") == 2
            assert "stale_build_cache" in text
        else:
            assert "src/collection/omni_hand" not in text
