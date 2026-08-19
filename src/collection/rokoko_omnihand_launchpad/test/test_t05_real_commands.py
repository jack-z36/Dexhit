from __future__ import annotations

import os
import time

import pytest

from rokoko_omnihand_launchpad import orchestrator as orchestrator_module
from rokoko_omnihand_launchpad.orchestrator import (
    Orchestrator,
    _resolve_profile_path,
    available_profiles,
    preflight,
)


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


def test_rokoko_receiver_rejects_any_port_except_14043():
    orchestrator = Orchestrator()
    try:
        with pytest.raises(ValueError, match="udp_port must be 14043"):
            orchestrator.configure({
                "blocks": ["rokoko_receiver"],
                "udp_port": 9000,
            })
    finally:
        orchestrator.close()


def test_rokoko_receiver_command_is_fixed_to_14043():
    receiver = Orchestrator._default_command(
        "rokoko_receiver",
        {"profile_data": {"commands": {"rokoko_receiver": ["ros2", "run", "receiver", "node"]}},
         "side": "left", "udp_port": 9000, "actor": 0},
    )
    assert "udp_port:=14043" in receiver
    assert "udp_port:=9000" not in receiver


def test_ros2_run_commands_scope_parameters_behind_ros_args():
    # 没有 --ros-args 时 rcl 会把 key:=value 解析成 remap，业务必填参数全部丢失
    # （provider/control 启动即退出的历史根因），必须先进入 ROS 参数作用域。
    orchestrator = Orchestrator()
    provider = orchestrator._command_factory(
        "hcan_provider",
        {"profile_data": {"commands": {"hcan_provider": ["ros2", "run", "adapter", "provider"]},
                          "parameters": {"hcan_provider": {"o10.left.transport": "hcan"}}},
         "side": "both"},
    )
    assert provider[:4] == ["ros2", "run", "adapter", "provider"]
    assert provider.index("--ros-args") < provider.index("o10.left.transport:=hcan")


def test_profile_params_path_expands_bash_style_default(monkeypatch):
    # os.path.expandvars 不认识 ${VAR:-default}；未展开的字面量路径曾直通
    # --params-file 导致重定向节点在 rcl init 崩溃。
    monkeypatch.delenv("DEXHIT_RETARGET_PARAMS", raising=False)
    assert _resolve_profile_path("${DEXHIT_RETARGET_PARAMS:-runs/retargeting_diag_params.yaml}") == (
        "runs/retargeting_diag_params.yaml"
    )
    monkeypatch.setenv("DEXHIT_RETARGET_PARAMS", "/abs/params.yaml")
    assert _resolve_profile_path("${DEXHIT_RETARGET_PARAMS:-runs/x.yaml}") == "/abs/params.yaml"
    assert _resolve_profile_path("$HOME") == os.path.expandvars("$HOME")


def test_starting_transitions_to_running_after_grace(tmp_path):
    orchestrator = Orchestrator(run_root=tmp_path, ready_grace=0.1)
    try:
        orchestrator.configure({"blocks": ["sim_provider"], "execution_mode": "stub"})
        orchestrator.start_node("sim_provider")
        assert orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] in {"starting", "running"}
        time.sleep(0.25)
        assert orchestrator.snapshot()["nodes"]["sim_provider"]["actual"] == "running"
    finally:
        orchestrator.close()


def _duplicate_flaky(calls, real):
    def flaky(blocks, *, side, profile="default", checks=None):
        calls["n"] += 1
        injected = {"ros2_available": True, "numeric_import": True,
                    "parameter_profile": True, "duplicate_nodes": calls["n"] > calls["first_pass"]}
        return real(blocks, side=side, profile=profile, checks=injected)
    return flaky


def test_start_all_settles_transient_duplicate_discovery(monkeypatch, tmp_path):
    """仅 duplicate_nodes 失败时应有界等待 DDS 清退，而不是立刻拒绝重启。"""
    calls = {"n": 0, "first_pass": 1}
    monkeypatch.setattr(orchestrator_module, "preflight",
                        _duplicate_flaky(calls, preflight))
    orchestrator = Orchestrator(run_root=tmp_path, duplicate_settle_timeout=3.0)
    try:
        orchestrator.configure({"blocks": ["rokoko_receiver"], "execution_mode": "real"})
        orchestrator.start_all()
        assert calls["n"] >= 2
        state = orchestrator.snapshot()["nodes"]["rokoko_receiver"]
        assert state["expected"] and state["pid"] is not None
    finally:
        orchestrator.close()


def test_start_all_fails_fast_on_persistent_duplicate(monkeypatch, tmp_path):
    calls = {"n": 0, "first_pass": 10}  # 永远失败
    monkeypatch.setattr(orchestrator_module, "preflight",
                        _duplicate_flaky(calls, preflight))
    orchestrator = Orchestrator(run_root=tmp_path, duplicate_settle_timeout=0.5)
    try:
        orchestrator.configure({"blocks": ["rokoko_receiver"], "execution_mode": "real"})
        started = time.monotonic()
        with pytest.raises(ValueError, match="preflight rejected"):
            orchestrator.start_all()
        assert time.monotonic() - started < 5.0
    finally:
        orchestrator.close()


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
