"""T11 seams for the explicit full-chain sim composition."""

from __future__ import annotations

from pathlib import Path

import pytest

from rokoko_omnihand_launchpad.orchestrator import Orchestrator, preflight
from rokoko_omnihand_launchpad.sim_provider import (
    SimProviderUnavailable,
    SoftwareO10Provider,
    command,
)


def test_software_provider_adapter_selects_public_system_test_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rokoko_omnihand_launchpad.sim_provider.shutil.which",
        lambda name: "/opt/ros/jazzy/bin/ros2" if name == "ros2" else None,
    )
    assert SoftwareO10Provider().command(side="left") == [
        "/opt/ros/jazzy/bin/ros2", "run", "rokoko_omnihand_system_test",
        "software_o10_provider",
    ]
    assert command(side="both")[-1] == "software_o10_provider"


def test_sim_provider_is_explicitly_blocked_without_ros2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rokoko_omnihand_launchpad.sim_provider.shutil.which", lambda _: None)
    with pytest.raises(SimProviderUnavailable, match="ros2 is not available"):
        command(side="right")


def test_sim_template_uses_real_business_nodes_and_keeps_hcan_mutual_exclusion() -> None:
    orchestrator = Orchestrator()
    snapshot = orchestrator.configure({
        "template": "sim",
        "blocks": ["rokoko_receiver", "hand_retargeting", "omnihand_o10_control", "sim_provider"],
        "side": "left",
    })
    assert snapshot["config"]["execution_mode"] == "sim"
    assert snapshot["config"]["blocks"][-1] == "sim_provider"
    assert not orchestrator.snapshot()["validation"]["errors"]
    with pytest.raises(ValueError, match="mutually exclusive"):
        orchestrator.configure({
            "template": "sim",
            "blocks": ["omnihand_o10_control", "hcan_provider", "sim_provider"],
        })
    orchestrator.close()


def test_real_profile_rejects_mock_only_system_test_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "unsafe.yaml"
    profile.write_text(
        "commands:\n  rokoko_receiver: [ros2, run, rokoko_omnihand_system_test, node]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEXHIT_LAUNCHPAD_PROFILES", str(tmp_path))
    with pytest.raises(ValueError, match="must not reference the system-test package"):
        Orchestrator().configure({
            "profile": "unsafe",
            "execution_mode": "real",
            "blocks": ["rokoko_receiver"],
        })


def test_sim_profile_allows_explicit_system_test_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "sim.yaml"
    profile.write_text(
        "commands:\n  sim_provider: [ros2, run, rokoko_omnihand_system_test, software_o10_provider]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEXHIT_LAUNCHPAD_PROFILES", str(tmp_path))
    snapshot = Orchestrator().configure({
        "profile": "sim",
        "execution_mode": "sim",
        "blocks": ["sim_provider"],
    })
    assert snapshot["config"]["execution_mode"] == "sim"
    assert snapshot["config"]["profile"] == "sim"


def test_sim_preflight_has_no_hardware_gate() -> None:
    result = preflight(
        ["rokoko_receiver", "hand_retargeting", "omnihand_o10_control", "sim_provider"],
        side="both",
        profile="default",
        checks={
            "ros2_available": True,
            "numeric_import": True,
            "parameter_profile": True,
            "duplicate_nodes": True,
            "sim_provider_available": True,
        },
    )
    assert result["passed"]
    assert "usb_canfd" not in result["required"]
