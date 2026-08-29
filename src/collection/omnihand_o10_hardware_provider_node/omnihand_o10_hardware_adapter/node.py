"""Thin ROS composition root for the production Provider shell."""

from __future__ import annotations

from collections.abc import Mapping

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
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

_SIDES_PARAM = "sides"
_DEFAULT_FEEDBACK_READ_PERIOD = 0.5


def _select_sides(value: object) -> tuple[Side, ...]:
    """
    Resolve the ``sides`` parameter into the ordered sides to wire up.
    """
    if value == "both":
        return (Side.LEFT, Side.RIGHT)
    if value == "left":
        return (Side.LEFT,)
    if value == "right":
        return (Side.RIGHT,)
    raise ValueError(
        f"unsupported 'sides' parameter value: {value!r} "
        "(expected both|left|right)"
    )


def _joint_command_qos(command_best_effort: bool) -> QoSProfile:
    """
    Historical Reliable depth-10 wire or the E2 best-effort probe link.
    """
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1 if command_best_effort else 10,
        reliability=(
            ReliabilityPolicy.BEST_EFFORT
            if command_best_effort
            else ReliabilityPolicy.RELIABLE
        ),
        durability=DurabilityPolicy.VOLATILE,
    )


class ProductionO10ProviderNode(Node):
    """Expose the fixed O10 topics and fresh-read service for each side.

    The default path is production-only: it declares all connection parameters,
    constructs both Agilink SDK backends, and fails startup if configuration or
    the external SDK is unavailable.  Tests may inject Applications directly.
    """

    def __init__(
        self,
        applications: Mapping[Side | str, object] | None = None,
        parameter_overrides=None,
    ):
        super().__init__(
            "omnihand_o10_hardware_provider", parameter_overrides=parameter_overrides
        )
        self.declare_parameter(_SIDES_PARAM, "both")
        selected_sides = _select_sides(self.get_parameter(_SIDES_PARAM).value)
        # Per-side diagnostic knobs (E2 command QoS, E3 feedback read period).
        # Declared for every selected side in both construction modes so the
        # behaviour is identical whether the SDK backends are real or injected.
        feedback_periods: dict[Side, float] = {}
        command_flags: dict[Side, bool] = {}
        for side in selected_sides:
            prefix = f"o10.{side.value}."
            feedback_periods[side] = float(
                self.declare_parameter(
                    f"{prefix}feedback_read_period",
                    _DEFAULT_FEEDBACK_READ_PERIOD,
                ).value
            )
            command_flags[side] = bool(
                self.declare_parameter(f"{prefix}command_best_effort", False).value
            )

        if applications is None:
            parameters = self._declare_production_parameters(selected_sides)
            self._applications = build_production_applications(
                parameters, sides=selected_sides
            )
        else:
            supplied = {
                Side.from_value(side): application for side, application in applications.items()
            }
            self._applications = {
                side: supplied.get(side, O10HardwareProviderApplication(side))
                for side in selected_sides
            }
        self._feedback_publishers = {}
        self._error_publishers = {}
        for side in selected_sides:
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
                _joint_command_qos(command_flags[side]),
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
        # boundary").  A non-positive period disables that periodic read for
        # the individual side (E3 diagnostic experiment) without touching any
        # other wiring.
        self._feedback_timers: dict[Side, object] = {}
        for side in selected_sides:
            if feedback_periods[side] > 0.0:
                self._feedback_timers[side] = self.create_timer(
                    feedback_periods[side],
                    lambda s=side: self._publish_feedback_periodic(s),
                )

    def _publish_feedback_periodic(self, side: Side) -> None:
        if side not in self._applications:
            return
        result = self._applications[side].read_active_joints()
        if result.success and result.value is not None:
            self.publish_feedback(result.value)

    def _declare_production_parameters(
        self, selected_sides: tuple[Side, ...]
    ) -> dict[str, object]:
        names: list[str] = []
        for side in selected_sides:
            for name, default in production_parameter_defaults(side).items():
                if self.has_parameter(name):
                    continue
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
