"""
Public-graph tests for the control-node command-link QoS switch.

Default wiring keeps today's profiles: Reliable depth-10 subscriptions on
``/o10_control/{side}/command`` and Reliable depth-10 publishers on
``/o10/{side}/joint_cmd``. Enabling ``{side}.command_link_best_effort``
switches BOTH endpoints of that side's command chain hop while leaving every
other endpoint untouched.

Reliability/durability are asserted through ROS graph discovery because that
is what remote hops must agree on; history depth is asserted against the
node-owned QoS construction helper directly (middleware discovery does not
reliably report reader depth).
"""

import time

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, HistoryPolicy, ReliabilityPolicy

from omnihand_o10_contracts import Side

from omnihand_o10_control.node import _command_qos
from omnihand_o10_control.node import O10ControlNode

from test_o10_control_node import make_config


_RELIABLE_VOLATILE = (
    ReliabilityPolicy.RELIABLE,
    DurabilityPolicy.VOLATILE,
)
_BEST_EFFORT_VOLATILE = (
    ReliabilityPolicy.BEST_EFFORT,
    DurabilityPolicy.VOLATILE,
)


def _params(**extra):
    from rclpy.parameter import Parameter

    return [Parameter(name=name, value=value) for name, value in extra.items()]


def test_default_command_qos_helper_keeps_depth10():
    profile = _command_qos(False)
    assert profile.reliability is ReliabilityPolicy.RELIABLE
    assert profile.durability is DurabilityPolicy.VOLATILE
    assert profile.depth == 10
    assert profile.history is HistoryPolicy.KEEP_LAST


def test_best_effort_command_qos_helper_is_sensor_data_like():
    profile = _command_qos(True)
    assert profile.reliability is ReliabilityPolicy.BEST_EFFORT
    assert profile.durability is DurabilityPolicy.VOLATILE
    assert profile.depth == 1
    assert profile.history is HistoryPolicy.KEEP_LAST


@pytest.fixture
def graph(request):
    overrides = getattr(request, "param", []) or []
    rclpy.init()
    try:
        control = O10ControlNode(
            left_config=make_config(Side.LEFT),
            right_config=make_config(Side.RIGHT),
            parameter_overrides=overrides,
        )
        observer = rclpy.create_node("control_qos_observer")
        executor = SingleThreadedExecutor()
        executor.add_node(observer)
        try:
            yield observer, executor
        finally:
            executor.shutdown()
            executor.remove_node(observer)
            observer.destroy_node()
            control.destroy_node()
    finally:
        rclpy.shutdown()


def _wait_for(executor, probe, topic, expected_count=1):
    deadline = time.monotonic() + 3.0
    infos = []
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.01)
        infos = probe(topic)
        if len(infos) >= expected_count:
            return infos
    return infos


_LEFT_COMMAND_TOPIC = "/o10_control/left/command"
_LEFT_JOINT_CMD_TOPIC = "/o10/left/joint_cmd"


@pytest.mark.parametrize("graph", [None], indirect=True)
def test_default_command_chain_stays_reliable(graph):
    observer, executor = graph
    subscribers = _wait_for(executor, observer.get_subscriptions_info_by_topic, _LEFT_COMMAND_TOPIC)
    assert len(subscribers) == 1
    assert (
        subscribers[0].qos_profile.reliability,
        subscribers[0].qos_profile.durability,
    ) == _RELIABLE_VOLATILE
    joint_cmd_pubs = _wait_for(
        executor, observer.get_publishers_info_by_topic, _LEFT_JOINT_CMD_TOPIC
    )
    assert len(joint_cmd_pubs) == 1
    assert (
        joint_cmd_pubs[0].qos_profile.reliability,
        joint_cmd_pubs[0].qos_profile.durability,
    ) == _RELIABLE_VOLATILE


@pytest.mark.parametrize(
    "graph",
    [_params(**{"left.command_link_best_effort": True})],
    indirect=True,
    ids=["left-best-effort"],
)
def test_left_command_link_best_effort_switches_both_left_endpoints(graph):
    observer, executor = graph
    subscribers = _wait_for(executor, observer.get_subscriptions_info_by_topic, _LEFT_COMMAND_TOPIC)
    assert len(subscribers) == 1
    assert (
        subscribers[0].qos_profile.reliability,
        subscribers[0].qos_profile.durability,
    ) == _BEST_EFFORT_VOLATILE

    joint_cmd_pubs = _wait_for(
        executor, observer.get_publishers_info_by_topic, _LEFT_JOINT_CMD_TOPIC
    )
    assert len(joint_cmd_pubs) == 1
    assert (
        joint_cmd_pubs[0].qos_profile.reliability,
        joint_cmd_pubs[0].qos_profile.durability,
    ) == _BEST_EFFORT_VOLATILE

    right_pubs = observer.get_publishers_info_by_topic("/o10/right/joint_cmd")
    assert len(right_pubs) == 1
    assert (
        right_pubs[0].qos_profile.reliability,
        right_pubs[0].qos_profile.durability,
    ) == _RELIABLE_VOLATILE, "the untouched side keeps its historical reliable wire"


def test_construction_without_any_qos_override_succeeds():
    """Sanity: no special parameters are required for plain construction."""
    rclpy.init()
    try:
        control = O10ControlNode(
            left_config=make_config(Side.LEFT), right_config=make_config(Side.RIGHT)
        )
        control.destroy_node()
    finally:
        rclpy.shutdown()
