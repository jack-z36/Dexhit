"""
Public-graph tests for the provider sides parameter and feedback period.

Default construction reproduces today behavior baseline: both sides wired
with one 0.5 s periodic startup feedback read per side. Selecting a side
wires and schedules only that side, and a non-positive feedback read period
stops that side periodic joint_states publication without disabling
anything else.
"""

import time

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
from sensor_msgs.msg import JointState

from omnihand_o10_contracts import JointFeedback, JointSampleTime, Side


class FakeSideApplication:
    """Duck-typed stand-in for O10HardwareProviderApplication reads."""

    def __init__(self, side: Side):
        self._side = side

    def read_active_joints(self):
        return _ReadResult(
            JointFeedback(self._side, (0.0,) * 10, JointSampleTime(time.time()))
        )

    def send_command(self, command):
        return _SimpleResult()

    def query_errors(self):
        return _FailingResult()


class _ReadResult:
    def __init__(self, value):
        self.success = True
        self.value = value
        self.message = "ok"


class _SimpleResult:
    success = True
    value = None
    message = "ok"


class _FailingResult:
    success = False
    value = None
    message = "unused in these tests"


def _overrides(**values):
    from rclpy.parameter import Parameter

    return [Parameter(name=name, value=value) for name, value in values.items()]


def _spin_until(executor, predicate, timeout_sec=3.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.01)
        if predicate():
            return True
    return predicate()


def test_default_joint_command_qos_helper_keeps_depth10():
    from omnihand_o10_hardware_adapter.node import _joint_command_qos

    profile = _joint_command_qos(False)
    assert profile.reliability is ReliabilityPolicy.RELIABLE
    assert profile.durability is DurabilityPolicy.VOLATILE
    assert profile.depth == 10
    assert profile.history is HistoryPolicy.KEEP_LAST


def test_best_effort_joint_command_qos_helper_is_sensor_data_like():
    from omnihand_o10_hardware_adapter.node import _joint_command_qos

    profile = _joint_command_qos(True)
    assert profile.reliability is ReliabilityPolicy.BEST_EFFORT
    assert profile.durability is DurabilityPolicy.VOLATILE
    assert profile.depth == 1
    assert profile.history is HistoryPolicy.KEEP_LAST


_LEFT_STATES = "/o10/left/joint_states"
_RIGHT_CMD_SUBS = "/o10/right/joint_cmd"


@pytest.fixture
def graph(request):
    overrides = getattr(request, "param", [])
    from omnihand_o10_hardware_adapter.node import ProductionO10ProviderNode

    rclpy.init()
    provider = ProductionO10ProviderNode(
        applications={side: FakeSideApplication(side) for side in Side},
        parameter_overrides=overrides,
    )
    observer = rclpy.create_node("provider_side_selection_observer")
    executor = SingleThreadedExecutor()
    executor.add_node(provider)
    executor.add_node(observer)
    try:
        yield provider, observer, executor
    finally:
        executor.shutdown()
        executor.remove_node(observer)
        executor.remove_node(provider)
        observer.destroy_node()
        provider.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


@pytest.mark.parametrize("graph", [_overrides(sides="both")], indirect=True)
def test_default_construction_wires_both_sides(graph):
    _, observer, _ = graph
    assert observer.count_subscribers("/o10/left/joint_cmd") == 1
    assert observer.count_subscribers(_RIGHT_CMD_SUBS) == 1
    assert observer.count_publishers(_LEFT_STATES) == 1
    assert observer.count_publishers("/o10/right/joint_states") == 1


@pytest.mark.parametrize("graph", [_overrides(sides="left")], indirect=True)
def test_sides_left_wires_only_the_left_side(graph):
    _, observer, _ = graph
    assert observer.count_subscribers("/o10/left/joint_cmd") == 1
    assert observer.count_subscribers(_RIGHT_CMD_SUBS) == 0
    assert observer.count_publishers(_LEFT_STATES) == 1
    assert observer.count_publishers("/o10/right/joint_states") == 0


@pytest.mark.parametrize(
    "graph",
    [_overrides(sides="both", **{"o10.left.feedback_read_period": 0.0})],
    indirect=True,
)
def test_zero_feedback_read_period_disables_that_side_publication(graph):
    _, observer, executor = graph
    states = []
    observer.create_subscription(JointState, _LEFT_STATES, states.append, 10)
    right_states = []
    observer.create_subscription(JointState, "/o10/right/joint_states", right_states.append, 10)

    def any_right_state():
        return len(right_states) >= 1

    # Positive control first: wait until the enabled side publishes at least
    # one periodic sample, so graph discovery has settled before judging the
    # disabled side.
    assert _spin_until(executor, any_right_state, timeout_sec=2.5), (
        "the still-enabled side keeps its periodic feedback publication"
    )

    # Now judge silence on the disabled side over >= two default periods.
    baseline_right = len(right_states)
    deadline = time.monotonic() + 1.6
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
    assert states == [], "disabled side must not publish periodic joint_states"
    assert len(right_states) > baseline_right, (
        "the still-enabled side must keep publishing during the silent window"
    )


@pytest.mark.parametrize("graph", [_overrides(sides="left")], indirect=True)
def test_default_period_publishes_joint_states_within_one_period(graph):
    _, observer, executor = graph
    states = []
    observer.create_subscription(JointState, _LEFT_STATES, states.append, 10)
    assert _spin_until(executor, lambda: len(states) >= 1, timeout_sec=2.5)


def test_invalid_sides_value_fails_construction():
    from omnihand_o10_hardware_adapter.node import ProductionO10ProviderNode

    rclpy.init()
    try:
        with pytest.raises(ValueError, match="sides"):
            ProductionO10ProviderNode(
                applications={side: FakeSideApplication(side) for side in Side},
                parameter_overrides=_overrides(sides="center"),
            )
    finally:
        if rclpy.ok():
            rclpy.shutdown()
