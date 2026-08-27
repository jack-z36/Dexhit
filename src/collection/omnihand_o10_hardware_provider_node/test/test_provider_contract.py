from __future__ import annotations

from pathlib import Path

from omnihand_o10_hardware_adapter.contracts import BLOCKED_EXTERNAL, BackendCode
from omnihand_o10_hardware_adapter.ports import O10HardwarePort


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT / "omnihand_o10_hardware_adapter"


def test_port_exposes_all_four_hardware_capabilities():
    methods = {
        name
        for name, member in O10HardwarePort.__dict__.items()
        if callable(member) and not name.startswith("_")
    }
    assert methods == {
        "send_command",
        "read_feedback",
        "query_errors",
        "read_active_joints",
    }


def test_blocked_external_is_machine_stable_and_not_success():
    assert BLOCKED_EXTERNAL == BackendCode.BLOCKED_EXTERNAL
    assert BLOCKED_EXTERNAL.value == "BLOCKED_EXTERNAL"
    assert BackendCode.BLOCKED_EXTERNAL is not BackendCode.SUCCESS


def test_production_adapter_owns_the_formal_vendor_boundary():
    """A09's vendor-free scan belongs to the software Provider package.

    The production adapter is the expressly permitted vendor boundary, so its
    SDK transport text must not be rejected by the software-Provider guard.
    The formal backend behavior is covered by ``test_agilink_backend.py``.
    """

    backend = (SOURCE_ROOT / "backends.py").read_text(encoding="utf-8")
    assert "class AgilinkO10Backend" in backend
    assert "get_all_active_joint_angles" in backend
    assert "get_error_report" in backend


def test_read_service_contract_is_the_fixed_no_motion_wire_shape():
    collection_root = PACKAGE_ROOT.parent
    service = (
        collection_root
        / "teleoperation_support"
        / "ros_interfaces"
        / "srv"
        / "ReadO10ActiveJoints.srv"
    ).read_text(
        encoding="utf-8"
    )
    assert service.startswith("# Empty request. Side is identified by the service name.")
    assert "float64[10] position" in service
    assert "uint8 READ_DEVICE_UNAVAILABLE=1" in service
    assert "uint8 READ_INTERNAL_ERROR=4" in service
