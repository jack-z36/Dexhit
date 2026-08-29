"""
Public-graph tests for the retargeting sides parameter and command QoS.

Default construction keeps both raw subscriptions, both state and command
publishers, and the historical Reliable depth-10 command wire. A selected
single side leaves the other side's endpoints absent, and the best-effort
switch changes exactly the command hop while the state topic stays reliable.

Reliability/durability come from ROS graph discovery; history depth comes
from direct introspection of the QoS construction helper because middleware
discovery does not reliably report reader/writer depth.
"""

import time

from hand_retargeting import node as node_module
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
from test_retargeting_node import _config_overrides, _geometry


def _wire_qos(info):
    return (
        info.qos_profile.reliability,
        info.qos_profile.durability,
    )


_RELIABLE_VOLATILE = (ReliabilityPolicy.RELIABLE, DurabilityPolicy.VOLATILE)
_BEST_EFFORT_VOLATILE = (ReliabilityPolicy.BEST_EFFORT, DurabilityPolicy.VOLATILE)


def _params(**extra):
    """Full required-config baseline plus optional experiment parameters."""
    from rclpy.parameter import Parameter

    return _config_overrides() + [
        Parameter(name=name, value=value) for name, value in extra.items()
    ]


def test_default_command_qos_helper_keeps_depth10():
    profile = node_module._command_qos(False)
    assert profile.reliability is ReliabilityPolicy.RELIABLE
    assert profile.durability is DurabilityPolicy.VOLATILE
    assert profile.depth == 10
    assert profile.history is HistoryPolicy.KEEP_LAST


def test_best_effort_command_qos_helper_is_sensor_data_like():
    profile = node_module._command_qos(True)
    assert profile.reliability is ReliabilityPolicy.BEST_EFFORT
    assert profile.durability is DurabilityPolicy.VOLATILE
    assert profile.depth == 1
    assert profile.history is HistoryPolicy.KEEP_LAST


@pytest.fixture
def graph(request):
    overrides = request.param if request.param is not None else []
    monkeypatch = request.getfixturevalue("monkeypatch")
    monkeypatch.setattr(node_module, "load_robot_geometry", lambda side: _geometry())
    monkeypatch.setattr(node_module, "load_runtime_assets", lambda side: object())
    monkeypatch.setattr(
        node_module, "load_pinocchio_kinematics",
        lambda assets, side: (_ for _ in ()).throw(
            node_module.PinocchioUnavailableError("BLOCKED_ENV: test")
        ),
    )
    rclpy.init()
    try:
        retargeter = node_module.HandRetargetingNode(parameter_overrides=overrides)
        observer = rclpy.create_node("retarget_sides_observer")
        executor = SingleThreadedExecutor()
        executor.add_node(retargeter)
        executor.add_node(observer)
        try:
            yield observer, executor
        finally:
            executor.shutdown()
            executor.remove_node(observer)
            executor.remove_node(retargeter)
            observer.destroy_node()
            retargeter.destroy_node()
    finally:
        rclpy.shutdown()


def _wait_for(executor, probe, topic):
    deadline = time.monotonic() + 3.0
    infos = []
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.01)
        infos = probe(topic)
        if infos:
            return infos
    return infos


_LEFT_COMMAND_TOPIC = "/o10_control/left/command"
_RIGHT_COMMAND_TOPIC = "/o10_control/right/command"
_LEFT_STATE_TOPIC = "/hand_retargeting/left/state"


@pytest.mark.parametrize("graph", [_params()], indirect=True)
def test_default_keeps_both_sides_and_the_historical_command_qos(graph):
    observer, executor = graph
    left_pubs = _wait_for(executor, observer.get_publishers_info_by_topic, _LEFT_COMMAND_TOPIC)
    assert len(left_pubs) == 1
    assert _wire_qos(left_pubs[0]) == _RELIABLE_VOLATILE
    right_pubs = _wait_for(
        executor, observer.get_publishers_info_by_topic, _RIGHT_COMMAND_TOPIC
    )
    assert len(right_pubs) == 1
    assert _wire_qos(right_pubs[0]) == _RELIABLE_VOLATILE
    assert len(observer.get_subscriptions_info_by_topic("/rokoko/left/raw_hand")) == 1
    assert len(observer.get_subscriptions_info_by_topic("/rokoko/right/raw_hand")) == 1


@pytest.mark.parametrize("graph", [_params(sides="left")], indirect=True)
def test_sides_left_removes_every_right_side_endpoint(graph):
    observer, executor = graph
    left_pubs = _wait_for(executor, observer.get_publishers_info_by_topic, _LEFT_COMMAND_TOPIC)
    assert len(left_pubs) == 1
    assert observer.get_publishers_info_by_topic(_RIGHT_COMMAND_TOPIC) == []
    assert observer.get_subscriptions_info_by_topic("/rokoko/right/raw_hand") == []
    assert observer.get_subscriptions_info_by_topic("/rokoko/left/raw_hand") != []


@pytest.mark.parametrize(
    "graph",
    [_params(sides="left", **{"left.command_best_effort": True})],
    indirect=True,
    ids=["left-best-effort"],
)
def test_command_best_effort_switches_only_that_side(graph):
    observer, executor = graph
    left_pubs = _wait_for(executor, observer.get_publishers_info_by_topic, _LEFT_COMMAND_TOPIC)
    assert len(left_pubs) == 1
    assert _wire_qos(left_pubs[0]) == _BEST_EFFORT_VOLATILE

    state_pubs = _wait_for(
        executor, observer.get_publishers_info_by_topic, _LEFT_STATE_TOPIC
    )
    assert len(state_pubs) == 1
    assert _wire_qos(state_pubs[0]) == _RELIABLE_VOLATILE, (
        "state diagnostics stay reliable"
    )


def test_invalid_sides_value_fails_construction(monkeypatch):
    monkeypatch.setattr(node_module, "load_robot_geometry", lambda side: _geometry())
    monkeypatch.setattr(node_module, "load_runtime_assets", lambda side: object())
    monkeypatch.setattr(
        node_module, "load_pinocchio_kinematics",
        lambda assets, side: (_ for _ in ()).throw(
            node_module.PinocchioUnavailableError("BLOCKED_ENV: test")
        ),
    )
    rclpy.init()
    try:
        with pytest.raises(ValueError, match="sides"):
            node_module.HandRetargetingNode(
                parameter_overrides=_params(sides="center")
            )
    finally:
        rclpy.shutdown()
