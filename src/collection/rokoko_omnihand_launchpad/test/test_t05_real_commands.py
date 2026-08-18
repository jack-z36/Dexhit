from __future__ import annotations

from rokoko_omnihand_launchpad.orchestrator import Orchestrator, available_profiles, preflight


def test_profiles_are_discoverable_and_data_link_uses_real_commands():
    assert {"default", "diagnostic"} <= set(available_profiles())
    orchestrator = Orchestrator()
    snapshot = orchestrator.configure({
        "blocks": ["rokoko_receiver", "hand_retargeting"],
        "side": "left",
        "profile": "diagnostic",
    })
    assert snapshot["config"]["execution_mode"] == "real"
    receiver = orchestrator._command_factory(
        "rokoko_receiver", {"profile_data": {"commands": {"rokoko_receiver": ["ros2", "run", "receiver", "node"]}},
                             "side": "left", "udp_port": 14043, "actor": 7}
    )
    assert receiver[:4] == ["ros2", "run", "receiver", "node"]
    assert "side:=left" in receiver and "udp_port:=14043" in receiver and "actor_index:=7" in receiver
    retargeting = orchestrator._command_factory(
        "hand_retargeting", {"profile_data": {"commands": {"hand_retargeting": ["bash"]}}, "side": "left"}
    )
    assert retargeting[0] == "bash"
    assert "hand_retargeting_node" in retargeting[1]
    assert "side:=left" in retargeting


def test_preflight_is_conditional_and_hcan_is_rejected_without_device():
    data_link = preflight(
        ["rokoko_receiver", "hand_retargeting"], side="left", profile="diagnostic",
        checks={"ros2_available": True, "numeric_import": True,
                "parameter_profile": True, "duplicate_nodes": True},
    )
    assert "usb_canfd" not in data_link["required"]
    assert data_link["passed"]
    real = preflight(
        ["rokoko_receiver", "hand_retargeting", "omnihand_o10_control", "hcan_provider"],
        side="both", profile="default",
        checks={"ros2_available": True, "numeric_import": True,
                "parameter_profile": True, "duplicate_nodes": True, "usb_canfd": False},
    )
    assert not real["passed"]
    assert "HCAN selected" in real["reasons"]["usb_canfd"]
