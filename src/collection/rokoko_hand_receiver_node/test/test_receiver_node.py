"""Loopback UDP to public RawHandFrame ROS seam behavior tests."""

import json
from pathlib import Path
import socket
import time

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, ReliabilityPolicy
from rokoko_omnihand_msgs.msg import RawHandFrame


FIXTURE = Path(__file__).parent / "fixtures" / "official_fields_constructed_v3.json"


def _available_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _spin_until(executor, predicate, timeout_sec=2.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.01)
        if predicate():
            return True
    return predicate()


def _fixture_object():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _send(port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(payload, ("127.0.0.1", port))


@pytest.fixture
def ros_graph():
    from rokoko_hand_receiver.node import RokokoHandReceiverNode

    port = _available_udp_port()
    rclpy.init()
    receiver = RokokoHandReceiverNode(
        parameter_overrides=[
            Parameter("bind_address", value="127.0.0.1"),
            Parameter("udp_port", value=port),
        ]
    )
    observer = Node("rokoko_hand_receiver_test_observer")
    executor = SingleThreadedExecutor()
    executor.add_node(receiver)
    executor.add_node(observer)
    try:
        yield port, receiver, observer, executor
    finally:
        executor.remove_node(observer)
        executor.remove_node(receiver)
        observer.destroy_node()
        receiver.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


def test_loopback_out_of_range_actor_index_still_publishes_both_sides():
    from rokoko_hand_receiver.node import RokokoHandReceiverNode

    port = _available_udp_port()
    rclpy.init()
    receiver = RokokoHandReceiverNode(
        parameter_overrides=[
            Parameter("bind_address", value="127.0.0.1"),
            Parameter("udp_port", value=port),
            # The fixture carries exactly one actor; a configured index that is
            # out of range must auto-resolve instead of dropping every scene.
            Parameter("actor_index", value=7),
        ]
    )
    observer = Node("rokoko_hand_receiver_test_observer")
    executor = SingleThreadedExecutor()
    executor.add_node(receiver)
    executor.add_node(observer)
    left_messages = []
    right_messages = []
    observer.create_subscription(
        RawHandFrame, "/rokoko/left/raw_hand", left_messages.append, 10
    )
    observer.create_subscription(
        RawHandFrame, "/rokoko/right/raw_hand", right_messages.append, 10
    )
    try:
        _send(port, FIXTURE.read_bytes())
        assert _spin_until(
            executor, lambda: len(left_messages) == 1 and len(right_messages) == 1
        )
        assert left_messages[0].actor_name == "DexhitFixtureActor"
        assert left_messages[0].actor_index == 0
        assert right_messages[0].actor_name == "DexhitFixtureActor"
    finally:
        executor.remove_node(observer)
        executor.remove_node(receiver)
        observer.destroy_node()
        receiver.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


def test_loopback_fixture_publishes_both_sides_with_shared_receive_time(ros_graph):
    port, _, observer, executor = ros_graph
    left_messages = []
    right_messages = []
    observer.create_subscription(
        RawHandFrame, "/rokoko/left/raw_hand", left_messages.append, 10
    )
    observer.create_subscription(
        RawHandFrame, "/rokoko/right/raw_hand", right_messages.append, 10
    )

    _send(port, FIXTURE.read_bytes())

    assert _spin_until(
        executor, lambda: len(left_messages) == 1 and len(right_messages) == 1
    )
    left = left_messages[0]
    right = right_messages[0]
    assert left.header.stamp == right.header.stamp
    assert left.header.frame_id == right.header.frame_id == "rokoko_world_y_up_z_forward"
    assert left.actor_index == right.actor_index == 0
    assert left.actor_name == right.actor_name == "DexhitFixtureActor"
    assert left.source_timestamp == right.source_timestamp == 1234.5
    assert left.node_names[0] == "leftHand"
    assert right.node_names[-1] == "rightLittleTip"
    assert left.positions[6].x == 6.0
    assert left.orientations[6].w == 2.0


def test_raw_publishers_offer_contract_qos(ros_graph):
    _, receiver, observer, executor = ros_graph

    assert _spin_until(
        executor,
        lambda: len(observer.get_publishers_info_by_topic("/rokoko/left/raw_hand")) == 1,
    )
    endpoint = observer.get_publishers_info_by_topic("/rokoko/left/raw_hand")[0]
    qos = endpoint.qos_profile
    assert qos.reliability == ReliabilityPolicy.RELIABLE
    assert qos.durability == DurabilityPolicy.VOLATILE
    # Fast DDS reports endpoint history/depth as UNKNOWN/0 through graph
    # introspection, so the public configurable depth is checked separately.
    assert receiver.get_parameter("raw_qos_depth").value == 10


@pytest.mark.parametrize("kept_side", ["left", "right"])
def test_loopback_single_side_scene_publishes_only_that_side(ros_graph, kept_side):
    port, _, observer, executor = ros_graph
    messages = {"left": [], "right": []}
    subscriptions = [
        observer.create_subscription(
            RawHandFrame,
            f"/rokoko/{side}/raw_hand",
            messages[side].append,
            10,
        )
        for side in ("left", "right")
    ]
    scene = _fixture_object()
    body = scene["scene"]["actors"][0]["body"]
    dropped_side = "right" if kept_side == "left" else "left"
    scene["scene"]["actors"][0]["body"] = {
        name: value for name, value in body.items() if not name.startswith(dropped_side)
    }

    _send(port, json.dumps(scene).encode())

    assert _spin_until(executor, lambda: len(messages[kept_side]) == 1)
    assert messages[dropped_side] == []
    assert subscriptions


@pytest.mark.parametrize(
    "corrupt_left",
    [
        lambda scene: scene["scene"]["actors"][0]["body"].pop("leftIndexTip"),
        lambda scene: scene["scene"]["actors"][0]["body"]["leftIndexTip"][
            "position"
        ].update(x=float("nan")),
        lambda scene: scene["scene"]["actors"][0]["body"]["leftIndexTip"][
            "rotation"
        ].update(w=0.0),
    ],
    ids=("missing", "nan", "invalid-quaternion"),
)
def test_loopback_bad_left_side_does_not_block_right(ros_graph, corrupt_left):
    port, _, observer, executor = ros_graph
    left_messages = []
    right_messages = []
    subscriptions = [
        observer.create_subscription(
            RawHandFrame, "/rokoko/left/raw_hand", left_messages.append, 10
        ),
        observer.create_subscription(
            RawHandFrame, "/rokoko/right/raw_hand", right_messages.append, 10
        ),
    ]
    scene = _fixture_object()
    corrupt_left(scene)

    _send(port, json.dumps(scene, allow_nan=True).encode())

    assert _spin_until(executor, lambda: len(right_messages) == 1)
    assert left_messages == []
    assert subscriptions


def test_loopback_duplicate_left_node_does_not_block_right(ros_graph):
    port, _, observer, executor = ros_graph
    left_messages = []
    right_messages = []
    subscriptions = [
        observer.create_subscription(
            RawHandFrame, "/rokoko/left/raw_hand", left_messages.append, 10
        ),
        observer.create_subscription(
            RawHandFrame, "/rokoko/right/raw_hand", right_messages.append, 10
        ),
    ]
    payload = FIXTURE.read_bytes().replace(
        b'"leftIndexTip":', b'"leftIndexTip": null, "leftIndexTip":', 1
    )

    _send(port, payload)

    assert _spin_until(executor, lambda: len(right_messages) == 1)
    assert left_messages == []
    assert subscriptions


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"version":3,"scene":{"timestamp":1,"actors":[]}}',
    ],
    ids=("invalid-json", "actor-absent"),
)
def test_loopback_scene_error_publishes_neither_side_and_receiver_survives(
    ros_graph, payload
):
    port, _, observer, executor = ros_graph
    left_messages = []
    right_messages = []
    subscriptions = [
        observer.create_subscription(
            RawHandFrame, "/rokoko/left/raw_hand", left_messages.append, 10
        ),
        observer.create_subscription(
            RawHandFrame, "/rokoko/right/raw_hand", right_messages.append, 10
        ),
    ]

    _send(port, payload)
    assert not _spin_until(
        executor,
        lambda: bool(left_messages or right_messages),
        timeout_sec=0.15,
    )
    _send(port, FIXTURE.read_bytes())
    assert _spin_until(
        executor, lambda: len(left_messages) == 1 and len(right_messages) == 1
    )
    assert subscriptions


def test_loopback_lz4_compressed_fixture_publishes_both_sides(ros_graph):
    import lz4.frame

    port, _, observer, executor = ros_graph
    left_messages = []
    right_messages = []
    subscriptions = [
        observer.create_subscription(
            RawHandFrame, "/rokoko/left/raw_hand", left_messages.append, 10
        ),
        observer.create_subscription(
            RawHandFrame, "/rokoko/right/raw_hand", right_messages.append, 10
        ),
    ]

    _send(port, lz4.frame.compress(FIXTURE.read_bytes()))

    assert _spin_until(
        executor, lambda: len(left_messages) == 1 and len(right_messages) == 1
    )
    assert left_messages[0].node_names[0] == "leftHand"
    assert left_messages[0].positions[6].x == 6.0
    assert right_messages[0].node_names[-1] == "rightLittleTip"
    assert subscriptions
