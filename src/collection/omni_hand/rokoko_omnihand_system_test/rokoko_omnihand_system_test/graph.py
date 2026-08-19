"""Public-interface ROS graph harness for T10.

The harness composes the real receiver, retargeting and control nodes with the
software Provider.  Tests communicate only through UDP, ROS Topics and ROS
Services; node implementation callbacks are never called directly.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rokoko_omnihand_msgs.msg import O10ControlState, RawHandFrame, RetargetingState
from rokoko_omnihand_msgs.srv import ControlOperation
from sensor_msgs.msg import JointState
from std_msgs.msg import Int16MultiArray, String

from hand_retargeting.node import HandRetargetingNode
from omnihand_o10_contracts import ACTIVE_JOINT_NAMES, Side
from omnihand_o10_control.contracts import ControlConfig
from omnihand_o10_control.node import O10ControlNode
from rokoko_hand_receiver.node import RokokoHandReceiverNode

from .provider import SoftwareO10ProviderNode
from .scenes import calibrated_scene_payload, scene_payload


def _retarget_parameter_overrides() -> list[Parameter]:
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
        Parameter("recovery_confirmation_timeout_sec", value=0.5),
    ]


def _control_config(side: Side, overrides=None) -> ControlConfig:
    values = dict(
        side=side,
        max_joint_rates=(1.0,) * 10,
        max_time_credit=0.1,
        slew_compare_epsilon=(1e-9,) * 10,
        target_input_stale_timeout=0.5,
        target_receive_stale_timeout=0.5,
        control_check_period=0.01,
        error_poll_period=0.03,
        error_query_timeout=0.03,
        command_readback_timeout=0.08,
        provider_heartbeat_timeout=0.5,
        init_read_retry_period=0.02,
        init_error_retry_period=0.02,
        read_service_timeout=0.04,
        clear_fault_error_timeout=0.05,
        clear_fault_read_timeout=0.05,
    )
    values.update(overrides or {})
    return ControlConfig(**values)


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class RosGraph:
    """A disposable, all-software ROS graph used by one test."""

    executor: MultiThreadedExecutor
    observer: Node
    receiver: RokokoHandReceiverNode
    retargeter: HandRetargetingNode
    control: O10ControlNode
    provider: SoftwareO10ProviderNode
    udp_port: int

    @classmethod
    def start(cls, *, control_overrides=None, **provider_kwargs) -> "RosGraph":
        # Pytest owns one process-wide context; standalone callers may still
        # start a graph in a fresh process.  Never re-initialize an active
        # context between disposable graphs.
        if not rclpy.ok():
            rclpy.init()
        udp_port = _free_udp_port()
        receiver = RokokoHandReceiverNode(
            parameter_overrides=[
                Parameter("bind_address", value="127.0.0.1"),
                Parameter("udp_port", value=udp_port),
            ]
        )
        retargeter = HandRetargetingNode(
            parameter_overrides=_retarget_parameter_overrides()
        )
        control = O10ControlNode(
            left_config=_control_config(
                Side.LEFT,
                (control_overrides or {}).get(Side.LEFT),
            ),
            right_config=_control_config(
                Side.RIGHT,
                (control_overrides or {}).get(Side.RIGHT),
            ),
        )
        provider = SoftwareO10ProviderNode(**provider_kwargs)
        observer = Node("t10_public_interface_observer")
        executor = MultiThreadedExecutor(num_threads=8)
        for node in (receiver, retargeter, control, provider, observer):
            executor.add_node(node)
        graph = cls(
            executor, observer, receiver, retargeter, control, provider, udp_port
        )
        graph.create_observers()
        return graph

    def create_observers(self) -> None:
        self.raw_frames = {"left": [], "right": []}
        self.raw_arrivals_ns = {"left": [], "right": []}
        self.retargeting_states = {"left": [], "right": []}
        self.state_arrivals_ns = {"left": [], "right": []}
        self.control_states = {"left": [], "right": []}
        self.final_commands = {"left": [], "right": []}
        self.soft_commands = {"left": [], "right": []}
        self.soft_command_arrivals_ns = {"left": [], "right": []}
        self.feedback = {"left": [], "right": []}
        self.error_states = {"left": [], "right": []}
        for side in ("left", "right"):
            self.observer.create_subscription(
                RawHandFrame,
                f"/rokoko/{side}/raw_hand",
                lambda message, selected=side: self._observe_raw(selected, message),
                10,
            )
            self.observer.create_subscription(
                RetargetingState,
                f"/hand_retargeting/{side}/state",
                lambda message, selected=side: self._observe_state(selected, message),
                10,
            )
            self.observer.create_subscription(
                JointState,
                f"/o10_control/{side}/command",
                lambda message, selected=side: self._observe_soft_command(
                    selected, message
                ),
                10,
            )
            self.observer.create_subscription(
                O10ControlState,
                f"/o10_control/{side}/state",
                self.control_states[side].append,
                10,
            )
            self.observer.create_subscription(
                JointState,
                f"/o10/{side}/joint_cmd",
                self.final_commands[side].append,
                10,
            )
            self.observer.create_subscription(
                JointState,
                f"/o10/{side}/joint_states",
                self.feedback[side].append,
                10,
            )
            self.observer.create_subscription(
                Int16MultiArray,
                f"/o10/{side}/joint_error_states",
                self.error_states[side].append,
                10,
            )
        self.target_publishers = {
            side: self.observer.create_publisher(
                JointState, f"/o10_control/{side.value}/command", 10
            )
            for side in (Side.LEFT, Side.RIGHT)
        }
        self.injection_publishers = {
            side: self.observer.create_publisher(
                String, f"/o10/{side.value}/test_injection", 10
            )
            for side in (Side.LEFT, Side.RIGHT)
        }
        self.operation_clients = {
            (side, operation): self.observer.create_client(
                ControlOperation,
                f"/o10_control/{side.value}/{operation}",
            )
            for side in (Side.LEFT, Side.RIGHT)
            for operation in ("clear_fault",)
        }

    def _observe_raw(self, side: str, message: RawHandFrame) -> None:
        self.raw_frames[side].append(message)
        self.raw_arrivals_ns[side].append(time.monotonic_ns())

    def _observe_state(self, side: str, message: RetargetingState) -> None:
        self.retargeting_states[side].append(message)
        self.state_arrivals_ns[side].append(time.monotonic_ns())

    def _observe_soft_command(self, side: str, message: JointState) -> None:
        self.soft_commands[side].append(message)
        self.soft_command_arrivals_ns[side].append(time.monotonic_ns())

    def spin_until(self, predicate, timeout_sec: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.01)
            if predicate():
                return True
        return bool(predicate())

    def send_scene(self, *, sequence: int = 0, left: bool = True, right: bool = True) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(
                scene_payload(sequence=sequence, left=left, right=right),
                ("127.0.0.1", self.udp_port),
            )

    def send_calibrated_scene(
        self, *, sequence: int = 0, left: bool = True, right: bool = True,
        invalid_finger: int | None = None, degenerate_palm: bool = False,
    ) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(
                calibrated_scene_payload(
                    sequence=sequence, left=left, right=right,
                    invalid_finger=invalid_finger,
                    degenerate_palm=degenerate_palm,
                ),
                ("127.0.0.1", self.udp_port),
            )

    def publish_target(self, side: Side, *, stamp=None) -> None:
        target = JointState()
        target.header.stamp = stamp or self.observer.get_clock().now().to_msg()
        target.name = list(ACTIVE_JOINT_NAMES)
        target.position = [0.0] * len(ACTIVE_JOINT_NAMES)
        self.target_publishers[side].publish(target)

    def inject(self, side: Side, mode: str) -> None:
        message = String()
        message.data = mode
        self.injection_publishers[side].publish(message)
        # Deliver the public injection command before the caller evaluates the
        # next public state transition. No node callback is called directly.
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.01)

    def call_operation(self, side: Side, operation: str, timeout_sec: float = 1.0):
        client = self.operation_clients[(side, operation)]
        assert self.spin_until(client.service_is_ready, timeout_sec), (
            f"service unavailable: {side.value}/{operation}"
        )
        future = client.call_async(ControlOperation.Request())
        assert self.spin_until(future.done, timeout_sec)
        return future.result()

    def close(self) -> None:
        nodes = (
            self.observer,
            self.provider,
            self.control,
            self.retargeter,
            self.receiver,
        )
        for node in nodes:
            self.executor.remove_node(node)
        for node in nodes:
            node.destroy_node()
        self.executor.shutdown(timeout_sec=2.0)
