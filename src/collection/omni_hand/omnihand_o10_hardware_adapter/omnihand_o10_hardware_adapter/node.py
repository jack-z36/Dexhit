"""Thin ROS composition root for the production Provider shell."""

from __future__ import annotations

from collections.abc import Mapping

import rclpy
from rclpy.node import Node
from rokoko_omnihand_msgs.srv import ReadO10ActiveJoints
from sensor_msgs.msg import JointState
from std_msgs.msg import Empty, Int16MultiArray

from omnihand_o10_contracts import Side

from .application.provider import O10HardwareProviderApplication
from .adapters.ros_wire import (
    errors_to_message,
    feedback_to_message,
    read_response_from_result,
    target_from_message,
)
from .composition import build_production_applications, production_parameter_defaults

__all__ = ["ProductionO10ProviderNode", "main"]


class ProductionO10ProviderNode(Node):
    """Expose the fixed O10 topics and fresh-read service for each side.

    The default path is production-only: it declares all connection parameters,
    constructs both Agilink SDK backends, and fails startup if configuration or
    the external SDK is unavailable.  Tests may inject Applications directly.
    """

    def __init__(self, applications: Mapping[Side | str, object] | None = None):
        super().__init__("omnihand_o10_hardware_provider")
        if applications is None:
            parameters = self._declare_production_parameters()
            self._applications = build_production_applications(parameters)
        else:
            supplied = {
                Side.from_value(side): application for side, application in applications.items()
            }
            self._applications = {
                side: supplied.get(side, O10HardwareProviderApplication(side))
                for side in (Side.LEFT, Side.RIGHT)
            }
        self._feedback_publishers = {}
        self._error_publishers = {}
        for side in (Side.LEFT, Side.RIGHT):
            self._feedback_publishers[side] = self.create_publisher(
                JointState, f"/o10/{side.value}/joint_states", 10
            )
            self._error_publishers[side] = self.create_publisher(
                Int16MultiArray, f"/o10/{side.value}/joint_error_states", 10
            )
            self.create_subscription(
                JointState,
                f"/o10/{side.value}/joint_cmd",
                lambda message, s=side: self._on_command(s, message),
                10,
            )
            self.create_subscription(
                Empty,
                f"/o10/{side.value}/joint_error_cmd",
                lambda request, s=side: self._on_error_query(s, request),
                10,
            )
            self.create_service(
                ReadO10ActiveJoints,
                f"/o10/{side.value}/read_active_joints",
                lambda request, response, s=side: self._on_read(s, request, response),
            )
        # The control node initialises its feedback limiter from a fresh
        # joint_states sample before arming. The vendor only publishes a
        # readback after a joint_cmd, so without a command there would never be
        # a startup feedback sample and the side could never be armed. Publish
        # the vendor's current active-joint positions periodically to provide
        # that independent startup read (documented O10 control contract:
        # "must supplement an independent startup read at the Adapter
        # boundary").
        self._feedback_timer = self.create_timer(
            0.5, self._publish_feedback_periodic
        )

    def _publish_feedback_periodic(self) -> None:
        for side in (Side.LEFT, Side.RIGHT):
            if side not in self._applications:
                continue
            result = self._applications[side].read_active_joints()
            if result.success and result.value is not None:
                self.publish_feedback(result.value)

    def _declare_production_parameters(self) -> dict[str, object]:
        names: list[str] = []
        for side in (Side.LEFT, Side.RIGHT):
            for name, default in production_parameter_defaults(side).items():
                self.declare_parameter(name, default)
                names.append(name)
        return {name: self.get_parameter(name).value for name in names}

    def _on_command(self, side: Side, message: JointState) -> None:
        try:
            command = target_from_message(side, message)
        except (TypeError, ValueError) as error:
            self.get_logger().error(f"rejected {side.value} command: {error}")
            return
        result = self._applications[side].send_command(command)
        if not result.success:
            self.get_logger().error(result.message)

    def _on_error_query(self, side: Side, _request: Empty) -> None:
        result = self._applications[side].query_errors()
        if not result.success:
            self.get_logger().error(result.message)
            return
        message = errors_to_message(result.value)
        self._error_publishers[side].publish(message)

    def _on_read(self, side: Side, _request, response):
        result = self._applications[side].read_active_joints()
        return read_response_from_result(result, response)

    def publish_feedback(self, feedback) -> None:
        """Publish one backend-supplied validated feedback sample."""

        self._feedback_publishers[feedback.side].publish(feedback_to_message(feedback))


def main(args=None):
    rclpy.init(args=args)
    node = ProductionO10ProviderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
