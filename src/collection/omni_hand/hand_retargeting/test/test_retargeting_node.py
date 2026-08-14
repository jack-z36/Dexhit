"""Public ROS graph tests for the T05 state transition seam."""

import math
import time

from geometry_msgs.msg import Point
from hand_retargeting import node as node_module
from hand_retargeting.core.normalization import RobotHandGeometry
from omnihand_o10_contracts import Side
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rokoko_omnihand_msgs.msg import RawHandFrame, RetargetingState


def _geometry():
    return RobotHandGeometry(
        finger_roots=tuple((float(index), 0.0, 0.0) for index in range(5)),
        finger_chain_lengths=(2.0, 3.0, 4.0, 5.0, 6.0),
        direction_mapping=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )


def _config_overrides():
    return [
        Parameter("palm_y_epsilon", value=1e-6),
        Parameter("palm_x_epsilon", value=1e-6),
        Parameter("finger_length_epsilon", value=1e-6),
        Parameter("length_window_size", value=3),
        Parameter("stable_window_count", value=2),
        Parameter("length_nmad_thresholds", value=[0.01] * 5),
        Parameter("frozen_length_relative_thresholds", value=[0.10] * 5),
        Parameter("ik_residual_thresholds", value=[0.05] * 5),
        Parameter("ik_max_evaluations", value=100),
        Parameter("ik_max_time_sec", value=0.02),
        Parameter("smooth_time_constants", value=[0.1] * 10),
        Parameter("stale_timeout_sec", value=0.5),
        Parameter("recovery_min_valid_frames", value=3),
        Parameter("recovery_min_duration_sec", value=0.1),
    ]


def _raw(side: Side, *, degenerate=False, stamp_ns=123):
    suffixes = (
        "Hand",
        "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    x_sign = 1.0 if side is Side.RIGHT else -1.0
    roots_x = (0.8, 0.6, 0.2, -0.2, -0.6)
    positions = [(0.0, 0.0, 0.0)]
    for root_x in roots_x:
        x = x_sign * root_x
        positions.extend(
            [(x, 1.0, 0.0), (x, 1.4, 0.0), (x, 1.8, 0.0), (x, 2.2, 0.0)]
        )
    if degenerate:
        for index in (5, 9, 13, 17):
            positions[index] = positions[0]
    message = RawHandFrame()
    message.header.stamp.sec = stamp_ns // 1_000_000_000
    message.header.stamp.nanosec = stamp_ns % 1_000_000_000
    message.node_names = [side.value + suffix for suffix in suffixes]
    message.positions = [
        Point(x=x, y=y, z=z)
        for x, y, z in positions
    ]
    return message


def _spin_until(executor, predicate, timeout_sec=2.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.01)
        if predicate():
            return True
    return predicate()


@pytest.fixture
def ros_graph(monkeypatch):
    monkeypatch.setattr(node_module, "load_robot_geometry", lambda side: _geometry())
    monkeypatch.setattr(node_module, "load_runtime_assets", lambda side: object())
    monkeypatch.setattr(
        node_module, "load_pinocchio_kinematics",
        lambda assets, side: (_ for _ in ()).throw(
            node_module.PinocchioUnavailableError("BLOCKED_ENV: test")
        ),
    )
    rclpy.init()
    retargeter = node_module.HandRetargetingNode(
        parameter_overrides=_config_overrides()
    )
    observer = Node("hand_retargeting_graph_test_observer")
    executor = SingleThreadedExecutor()
    executor.add_node(retargeter)
    executor.add_node(observer)
    try:
        yield retargeter, observer, executor
    finally:
        executor.remove_node(observer)
        executor.remove_node(retargeter)
        observer.destroy_node()
        retargeter.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


def test_public_state_topic_observes_collecting_to_waiting_without_command(ros_graph):
    _, observer, executor = ros_graph
    states = []
    raw_publisher = observer.create_publisher(RawHandFrame, "/rokoko/right/raw_hand", 10)
    observer.create_subscription(
        RetargetingState, "/hand_retargeting/right/state", states.append, 10
    )
    for expected_count in range(1, 5):
        raw_publisher.publish(_raw(Side.RIGHT))
        assert _spin_until(executor, lambda: len(states) >= expected_count)
    assert [state.phase for state in states[-4:]] == [
        RetargetingState.PHASE_COLLECTING_LENGTHS,
        RetargetingState.PHASE_COLLECTING_LENGTHS,
        RetargetingState.PHASE_COLLECTING_LENGTHS,
        RetargetingState.PHASE_WAITING_FIRST_VALID_IK,
    ]
    waiting = states[-1]
    assert waiting.side == "right"
    assert waiting.solve_executed is False
    assert math.isnan(waiting.solve_duration_sec)
    assert waiting.input_stamp.sec == 0
    assert waiting.input_stamp.nanosec == 123
    assert waiting.command_published is False
    assert list(waiting.ik_state) == [RetargetingState.IK_UNINITIALIZED] * 5
    assert list(waiting.residual_available) == [False] * 5
    assert all(math.isnan(value) for value in waiting.normalized_residual)
    assert list(waiting.solver_result_code) == list(RetargetingState().solver_result_code)
    assert list(waiting.solver_evaluations) == [0] * 5


def test_public_topics_keep_left_and_right_length_aggregates_isolated(ros_graph):
    _, observer, executor = ros_graph
    states = {"left": [], "right": []}
    publishers = {}
    for side in ("left", "right"):
        publishers[side] = observer.create_publisher(
            RawHandFrame, f"/rokoko/{side}/raw_hand", 10
        )
        observer.create_subscription(
            RetargetingState,
            f"/hand_retargeting/{side}/state",
            states[side].append,
            10,
        )
    for expected_count in range(1, 5):
        publishers["left"].publish(_raw(Side.LEFT))
        assert _spin_until(executor, lambda: len(states["left"]) >= expected_count)
    publishers["right"].publish(_raw(Side.RIGHT))
    assert _spin_until(executor, lambda: len(states["right"]) >= 1)
    assert states["left"][-1].phase == RetargetingState.PHASE_WAITING_FIRST_VALID_IK
    assert states["right"][-1].phase == RetargetingState.PHASE_COLLECTING_LENGTHS


def test_public_topic_reports_palm_degeneracy_without_running_ik(ros_graph):
    _, observer, executor = ros_graph
    states = []
    publisher = observer.create_publisher(RawHandFrame, "/rokoko/right/raw_hand", 10)
    observer.create_subscription(
        RetargetingState, "/hand_retargeting/right/state", states.append, 10
    )
    publisher.publish(_raw(Side.RIGHT, degenerate=True))
    assert _spin_until(executor, lambda: bool(states))
    state = states[-1]
    assert state.phase == RetargetingState.PHASE_COLLECTING_LENGTHS
    assert list(state.length_state) == [RetargetingState.LENGTH_COLLECTING] * 5
    assert list(state.ik_state) == [RetargetingState.IK_NOT_RUN_LENGTH_COLLECTING] * 5
    assert state.solve_executed is False
    assert math.isnan(state.solve_duration_sec)
    assert state.input_stamp.sec == 0
    assert state.input_stamp.nanosec == 123


def test_public_topic_reports_model_error(monkeypatch):
    def fail(_side):
        raise node_module.RobotGeometryLoadError("fixture model failure")

    monkeypatch.setattr(node_module, "load_robot_geometry", fail)
    rclpy.init()
    retargeter = node_module.HandRetargetingNode(parameter_overrides=_config_overrides())
    observer = Node("hand_retargeting_model_error_test_observer")
    executor = SingleThreadedExecutor()
    executor.add_node(retargeter)
    executor.add_node(observer)
    states = []
    publisher = observer.create_publisher(RawHandFrame, "/rokoko/right/raw_hand", 10)
    observer.create_subscription(
        RetargetingState, "/hand_retargeting/right/state", states.append, 10
    )
    try:
        publisher.publish(_raw(Side.RIGHT))
        assert _spin_until(executor, lambda: bool(states))
        assert states[-1].phase == RetargetingState.PHASE_MODEL_ERROR
        assert states[-1].side == "right"
        assert states[-1].input_stamp.sec == 0
        assert states[-1].input_stamp.nanosec == 123
        assert states[-1].solve_executed is False
        assert math.isnan(states[-1].solve_duration_sec)
        assert list(states[-1].solver_result_code) == list(
            RetargetingState().solver_result_code
        )
    finally:
        executor.remove_node(observer)
        executor.remove_node(retargeter)
        observer.destroy_node()
        retargeter.destroy_node()
        executor.shutdown()
        rclpy.shutdown()
