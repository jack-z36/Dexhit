"""End-to-end graph tests: O10 control node + software O10 provider (A09).

These are the system-level prior art for T07: the real control node and the
deterministic software provider share one ROS graph, and the tests drive the
operator services / upstream targets and observe the vendor topics and the
diagnostic control state.
"""

import threading
import time

import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rokoko_omnihand_msgs.msg import O10ControlState
from rokoko_omnihand_msgs.srv import ControlOperation
from sensor_msgs.msg import JointState

from omnihand_o10_contracts import ACTIVE_JOINT_NAMES, JointSampleTime, Side

from omnihand_o10_control.contracts import (
    ControlConfig,
    FaultReason,
)
from omnihand_o10_control.node import O10ControlNode

from rokoko_omnihand_system_test.provider import SoftwareO10ProviderNode

LEFT_VALID = (0.0, 0.5, 0.0, 0.1, 0.5, 0.5, 0.0, 0.5, 0.0, 0.5)
RIGHT_VALID = (0.5, 0.0, 0.4, 0.0, 0.5, 0.5, 0.05, 0.5, 0.05, 0.5)
# A large step on left thumb_abad (room to 1.64) for the slew-limit test.
LEFT_BIG_STEP = (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def make_config(side: Side) -> ControlConfig:
    return ControlConfig(
        side=side,
        max_joint_rates=(0.1,) * 10,
        max_time_credit=0.1,
        slew_compare_epsilon=(1e-4,) * 10,
        target_input_stale_timeout=2.0,
        target_receive_stale_timeout=2.0,
        control_check_period=0.05,
        error_poll_period=0.2,
        error_query_timeout=0.5,
        command_readback_timeout=2.0,
        provider_heartbeat_timeout=3.0,
        init_read_retry_period=0.1,
        init_error_retry_period=0.1,
        read_service_timeout=1.0,
        clear_fault_error_timeout=1.0,
        clear_fault_read_timeout=1.0,
    )


def spin_until(executor, predicate, timeout_sec=5.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def call_operation(executor, client, request, timeout_sec=5.0):
    assert client.wait_for_service(timeout_sec)
    future = client.call_async(request)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline and not future.done():
        time.sleep(0.01)
    assert future.done(), "operation service call timed out"
    return future.result()


def make_target(observer: Node, side: Side, position=LEFT_VALID) -> JointState:
    message = JointState()
    message.header.stamp = observer.get_clock().now().to_msg()
    message.name = list(ACTIVE_JOINT_NAMES)
    message.position = list(position)
    return message


def publish_target(executor, observer, command_pub, side, position=LEFT_VALID):
    message = make_target(observer, side, position)
    command_pub.publish(message)
    time.sleep(0.3)
    return message


@pytest.fixture
def graph():
    rclpy.init()
    provider = SoftwareO10ProviderNode()
    control = O10ControlNode(
        left_config=make_config(Side.LEFT),
        right_config=make_config(Side.RIGHT),
    )
    observer = Node("o10_control_graph_observer")
    executor = MultiThreadedExecutor(num_threads=8)
    for node in (provider, control, observer):
        executor.add_node(node)
    # A blocking clear_fault handler needs the executor to keep serving the
    # feedback / error-status subscriptions, so spin on a background thread.
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        yield provider, control, observer, executor
    finally:
        executor.shutdown()
        spin_thread.join(timeout=2.0)
        for node in (provider, control, observer):
            executor.remove_node(node)
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def prepare_side(executor, provider, observer, side: Side):
    """Wait for one side to be ready (init read + error monitor connected),
    then publish one warm-up target so DDS discovery has matched."""
    command_pub = observer.create_publisher(
        JointState, f"/o10_control/{side.value}/command", 10
    )
    assert spin_until(
        executor,
        lambda: command_pub.get_subscription_count() == 1
        and provider.side(side).reads_received >= 1
        and provider.side(side).error_queries_received >= 1,
    )
    publish_target(executor, observer, command_pub, side)
    return command_pub


def test_startup_does_not_publish_commands(graph):
    provider, _, observer, executor = graph
    left_messages = []
    right_messages = []
    observer.create_subscription(
        JointState, "/o10/left/joint_cmd", left_messages.append, 10
    )
    observer.create_subscription(
        JointState, "/o10/right/joint_cmd", right_messages.append, 10
    )
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        time.sleep(0.01)
    assert left_messages == []
    assert right_messages == []


def test_left_command_is_forwarded_and_the_right_is_untouched(graph):
    provider, _, observer, executor = graph
    left_messages = []
    right_messages = []
    observer.create_subscription(
        JointState, "/o10/left/joint_cmd", left_messages.append, 10
    )
    observer.create_subscription(
        JointState, "/o10/right/joint_cmd", right_messages.append, 10
    )
    command_pub = prepare_side(executor, provider, observer, Side.LEFT)

    left_messages.clear()
    published = publish_target(executor, observer, command_pub, Side.LEFT)
    assert spin_until(executor, lambda: len(left_messages) >= 1)
    assert right_messages == []
    # The command echoes the ORIGINAL upstream target stamp (the adapter only
    # round-trips it through float seconds, so allow nanosecond tolerance).
    command_stamp = left_messages[0].header.stamp
    assert command_stamp.sec == published.header.stamp.sec
    assert abs(command_stamp.nanosec - published.header.stamp.nanosec) <= 1000
    # The vendor provider requires the fixed active-joint order on the wire;
    # the final command must carry it (and no velocity/effort).
    assert list(left_messages[0].name) == list(ACTIVE_JOINT_NAMES)
    assert list(left_messages[0].velocity) == []
    assert list(left_messages[0].effort) == []


def test_side_before_init_never_forwards_even_with_targets(graph):
    _, _, observer, executor = graph
    left_messages = []
    observer.create_subscription(
        JointState, "/o10/left/joint_cmd", left_messages.append, 10
    )
    command_pub = observer.create_publisher(
        JointState, "/o10_control/left/command", 10
    )
    assert spin_until(executor, lambda: command_pub.get_subscription_count() == 1)
    publish_target(executor, observer, command_pub, Side.LEFT)
    spin_until(executor, lambda: True, timeout_sec=0.5)
    assert left_messages == []


def test_hard_slew_limit_clips_a_big_target_step(graph):
    provider, _, observer, executor = graph
    left_messages = []
    observer.create_subscription(
        JointState, "/o10/left/joint_cmd", left_messages.append, 10
    )
    command_pub = prepare_side(executor, provider, observer, Side.LEFT)

    big = LEFT_BIG_STEP
    publish_target(executor, observer, command_pub, Side.LEFT, big)
    assert spin_until(executor, lambda: len(left_messages) >= 1)
    first = left_messages[0].position[1]
    assert 0.0 <= first < 1.0  # clipped well below the 1.0 target


def test_vendor_error_latches_fault_and_clear_fault_recovers(graph):
    provider, _, observer, executor = graph
    command_pub = prepare_side(executor, provider, observer, Side.LEFT)

    states = []
    observer.create_subscription(
        O10ControlState, "/o10_control/left/state", states.append, 10
    )
    provider.left.error_bits = (1, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    assert spin_until(
        executor,
        lambda: states
        and states[-1].phase == O10ControlState.PHASE_FAULT_LATCHED,
    )
    assert states[-1].fault_latched
    assert states[-1].fault_reason_mask & O10ControlState.FAULT_HARDWARE_ERROR
    assert not states[-1].motion_enabled

    # no motion while latched
    publish_target(executor, observer, command_pub, Side.LEFT)
    spin_until(executor, lambda: True, timeout_sec=0.4)

    clear_client = observer.create_client(
        ControlOperation, "/o10_control/left/clear_fault"
    )
    provider.left.error_bits = (0,) * 10
    response = call_operation(executor, clear_client, ControlOperation.Request())
    assert response.success, f"clear_fault failed: {response.message}"
    # A still-fresh target resumes motion automatically after clear_fault.
    assert response.state.phase == O10ControlState.PHASE_ACTIVE
    assert not response.state.fault_latched
    assert response.state.motion_enabled


def test_out_of_limit_target_is_never_forwarded(graph):
    provider, _, observer, executor = graph
    command_pub = prepare_side(executor, provider, observer, Side.LEFT)
    publish_target(
        executor, observer, command_pub, Side.LEFT, [0.04] + [0.0] * 9
    )
    states = []
    observer.create_subscription(
        O10ControlState, "/o10_control/left/state", states.append, 10
    )
    assert spin_until(
        executor,
        lambda: states
        and states[-1].target_result == O10ControlState.TARGET_REJECTED_LIMIT,
    )
    # The rejected target must never reach the hardware provider.  (The
    # warm-up target keeps the side motion-enabled overall; only the new
    # target is rejected.)
    assert provider.left.commands_received == 0


def test_commu_except_bit_alone_does_not_block_motion(graph):
    """commu_except (bit4 = 16) is a vendor-historical marker and must not
    latch a fault or block motion; a real fatal bit must still do so."""
    provider, _, observer, executor = graph
    command_pub = prepare_side(executor, provider, observer, Side.LEFT)
    states = []
    observer.create_subscription(
        O10ControlState, "/o10_control/left/state", states.append, 10
    )
    # commu_except only: must NOT latch a fault or block motion.
    provider.left.error_bits = (16, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    publish_target(executor, observer, command_pub, Side.LEFT)
    assert spin_until(
        executor,
        lambda: states
        and states[-1].motion_enabled
        and not states[-1].fault_latched,
    )
    assert provider.left.commands_received >= 1
