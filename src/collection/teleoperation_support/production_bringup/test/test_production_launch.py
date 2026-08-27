"""Structural tests for the production-only composition boundary."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "launch" / "production.launch.py"


def test_production_launch_has_explicit_required_inputs_and_no_test_provider():
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument(\n                "parameters"' in source
    assert 'DeclareLaunchArgument(\n                "vendor_launch"' in source
    assert "default_value" not in source
    assert "system_test" not in source
    assert "SoftwareO10Provider" not in source
    assert 'package="rokoko_hand_receiver"' in source
    assert 'package="hand_retargeting"' in source
    assert 'package="omnihand_o10_control"' in source
    assert 'package="omnihand_o10_hardware_adapter"' in source


def test_bringup_manifest_does_not_depend_on_system_test():
    manifest = (ROOT / "package.xml").read_text(encoding="utf-8")
    assert "rokoko_omnihand_system_test" not in manifest
