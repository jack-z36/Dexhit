"""Deterministic in-process O10 software provider (ARCHITECTURE A09, A04).

This node emulates the OmniHand O10 wire contract (vendor trigger-based readback,
``jazzy/.../omnihand_2025``) WITHOUT any dependency on the vendor ``omnihand_node``
package or hardware.  It lets the O10 control system and its integration tests
run end-to-end on a laptop with full control over every message the control node
can receive.

Injection knobs (per side, settable at construction and at runtime):

* ``initial_position`` -- the position returned by ``read_active_joints`` and
  used to seed the control slew limiter;
* ``error_bits`` -- the 10 vendor error words echoed on an error query;
* ``reply_to_error_query`` -- if False, an error query is silently dropped
  (drives the error-monitor timeout path);
* ``reply_to_read`` -- if False, a read request is left unanswered (drives the
  read timeout / retry path);
* ``publish_feedback_after_command`` -- if False, no ``joint_states`` readback
  is produced after a ``joint_cmd`` (drives the command-readback timeout path);
* ``feedback_invalid`` -- ``"nonfinite"`` / ``"wrong_dim"`` to make the readback
  illegal (drives the illegal-feedback fault path);
* ``error_invalid`` -- ``"wrong_dim"`` to make the error-status message illegal.
* ``/o10/{side}/test_injection`` -- public test-only String topic. Values are
  ``healthy``, ``error_bits``, ``error_query_timeout``,
  ``feedback_read_timeout``, ``command_readback_timeout``,
  ``invalid_feedback``, ``invalid_error_status``, ``disconnect`` and
  ``restart``.

The restart/disconnect modes model provider availability only. They do not
restart a process, touch a device, or claim to reproduce hardware timing.
"""

from __future__ import annotations

import math
import time

import rclpy
from rclpy.node import Node
from rokoko_omnihand_msgs.srv import ReadO10ActiveJoints
from sensor_msgs.msg import JointState
from std_msgs.msg import Empty, Int16MultiArray, String

from omnihand_o10_contracts import ACTIVE_JOINT_COUNT, Side

__all__ = ["SoftwareO10ProviderNode", "main"]


class _ProviderSide:
    def __init__(
        self,
        node: Node,
        side: Side,
        *,
        initial_position=(0.0,) * ACTIVE_JOINT_COUNT,
        error_bits=(0,) * ACTIVE_JOINT_COUNT,
        reply_to_error_query=True,
        reply_to_read=True,
        publish_feedback_after_command=True,
        feedback_invalid=None,
        error_invalid=None,
        restart_after_commands=None,
        disconnect_after_commands=None,
        restart_duration_sec=1.0,
    ):
        self.side = side
        self.initial_position = tuple(float(v) for v in initial_position)
        self.error_bits = tuple(int(v) for v in error_bits)
        self.reply_to_error_query = reply_to_error_query
        self.reply_to_read = reply_to_read
        self.publish_feedback_after_command = publish_feedback_after_command
        self.feedback_invalid = feedback_invalid
        self.error_invalid = error_invalid
        self._restart_after_commands = restart_after_commands
        self._disconnect_after_commands = disconnect_after_commands
        self._restart_duration_sec = float(restart_duration_sec)
        self._connected = True
        self._restart_until = None
        self._availability_injected = False

        self._node = node
        self._logger = node.get_logger()
        self.commands_received = 0
        self.error_queries_received = 0
        self.reads_received = 0

        self._joint_cmd_sub = node.create_subscription(
            JointState,
            f"/o10/{side.value}/joint_cmd",
            self._on_joint_cmd,
            10,
        )
        self._error_cmd_sub = node.create_subscription(
            Empty,
            f"/o10/{side.value}/joint_error_cmd",
            self._on_error_cmd,
            10,
        )
        self._injection_sub = node.create_subscription(
            String,
            f"/o10/{side.value}/test_injection",
            self._on_injection,
            10,
        )
        self._joint_states_pub = node.create_publisher(
            JointState, f"/o10/{side.value}/joint_states", 10
        )
        self._error_states_pub = node.create_publisher(
            Int16MultiArray, f"/o10/{side.value}/joint_error_states", 10
        )
        self._read_service = node.create_service(
            ReadO10ActiveJoints,
            f"/o10/{side.value}/read_active_joints",
            self._on_read,
        )
        self._restart_timer = node.create_timer(0.01, self._restore_after_restart)

    def _restore_after_restart(self) -> None:
        if (
            not self._connected
            and self._restart_until is not None
            and time.monotonic() >= self._restart_until
        ):
            self._connected = True
            self._restart_until = None
            self._availability_injected = True

    def _on_injection(self, message: String) -> None:
        mode = message.data.strip().lower()
        if mode == "healthy":
            self._connected = True
            self._restart_until = None
            self.reply_to_error_query = True
            self.reply_to_read = True
            self.publish_feedback_after_command = True
            self.feedback_invalid = None
            self.error_invalid = None
            self.error_bits = (0,) * ACTIVE_JOINT_COUNT
        elif mode == "error_bits":
            self.error_bits = (1,) + (0,) * (ACTIVE_JOINT_COUNT - 1)
        elif mode == "error_query_timeout":
            self.reply_to_error_query = False
        elif mode == "feedback_read_timeout":
            self.reply_to_read = False
        elif mode == "command_readback_timeout":
            self.publish_feedback_after_command = False
        elif mode == "invalid_feedback":
            self.feedback_invalid = "nonfinite"
        elif mode == "invalid_error_status":
            self.error_invalid = "wrong_dim"
        elif mode == "disconnect":
            self._connected = False
            self._restart_until = None
        elif mode == "restart":
            self._connected = False
            self._restart_until = time.monotonic() + self._restart_duration_sec
        else:
            self._logger.warning(f"ignored unknown test injection: {message.data!r}")

    def _maybe_inject_availability_failure(self) -> None:
        if self._availability_injected:
            return
        if (
            self._disconnect_after_commands is not None
            and self.commands_received >= self._disconnect_after_commands
        ):
            self._connected = False
            self._availability_injected = True
        elif (
            self._restart_after_commands is not None
            and self.commands_received >= self._restart_after_commands
        ):
            self._connected = False
            self._restart_until = time.monotonic() + self._restart_duration_sec
            self._availability_injected = True

    def _on_joint_cmd(self, message: JointState) -> None:
        self.commands_received += 1
        self._maybe_inject_availability_failure()
        if not self._connected:
            return
        if not self.publish_feedback_after_command:
            return
        output = JointState()
        output.header = message.header
        if self.feedback_invalid == "nonfinite":
            output.position = [math.nan] * ACTIVE_JOINT_COUNT
        elif self.feedback_invalid == "wrong_dim":
            output.position = [0.0] * (ACTIVE_JOINT_COUNT - 1)
        else:
            output.position = list(message.position)
        self._joint_states_pub.publish(output)

    def _on_error_cmd(self, message: Empty) -> None:
        self.error_queries_received += 1
        if not self._connected or not self.reply_to_error_query:
            return
        output = Int16MultiArray()
        if self.error_invalid == "wrong_dim":
            output.data = list(self.error_bits[: ACTIVE_JOINT_COUNT - 1])
        else:
            output.data = list(self.error_bits)
        self._error_states_pub.publish(output)

    def _on_read(self, request, response):
        self.reads_received += 1
        if not self._connected or not self.reply_to_read:
            # Leave the client future unresolved.
            return response
        response.success = True
        response.result_code = ReadO10ActiveJoints.Response.READ_SUCCESS
        response.message = "software provider read"
        now = self._node.get_clock().now()
        response.sample_stamp = now.to_msg()
        if self.feedback_invalid == "nonfinite":
            response.position = [math.nan] * ACTIVE_JOINT_COUNT
        else:
            response.position = list(self.initial_position)
        return response


class SoftwareO10ProviderNode(Node):
    """Deterministic dual-hand software provider for O10 integration tests."""

    def __init__(
        self,
        *,
        initial_positions=None,
        error_bits=None,
        reply_to_error_query=None,
        reply_to_read=None,
        publish_feedback_after_command=None,
        feedback_invalid=None,
        error_invalid=None,
        restart_after_commands=None,
        disconnect_after_commands=None,
        restart_duration_sec=None,
    ):
        super().__init__("software_o10_provider")
        self._sides = {}
        for side in (Side.LEFT, Side.RIGHT):
            self._sides[side] = _ProviderSide(
                self,
                side,
                initial_position=(
                    initial_positions.get(side, (0.0,) * ACTIVE_JOINT_COUNT)
                    if initial_positions
                    else (0.0,) * ACTIVE_JOINT_COUNT
                ),
                error_bits=(
                    error_bits.get(side, (0,) * ACTIVE_JOINT_COUNT)
                    if error_bits
                    else (0,) * ACTIVE_JOINT_COUNT
                ),
                reply_to_error_query=(
                    reply_to_error_query.get(side, True)
                    if reply_to_error_query
                    else True
                ),
                reply_to_read=(
                    reply_to_read.get(side, True) if reply_to_read else True
                ),
                publish_feedback_after_command=(
                    publish_feedback_after_command.get(side, True)
                    if publish_feedback_after_command
                    else True
                ),
                feedback_invalid=(
                    feedback_invalid.get(side) if feedback_invalid else None
                ),
                error_invalid=(error_invalid.get(side) if error_invalid else None),
                restart_after_commands=(
                    restart_after_commands.get(side)
                    if restart_after_commands
                    else None
                ),
                disconnect_after_commands=(
                    disconnect_after_commands.get(side)
                    if disconnect_after_commands
                    else None
                ),
                restart_duration_sec=(
                    restart_duration_sec.get(side, 1.0)
                    if restart_duration_sec
                    else 1.0
                ),
            )

    def side(self, side: Side | str) -> _ProviderSide:
        return self._sides[Side.from_value(side)]

    @property
    def left(self) -> _ProviderSide:
        return self._sides[Side.LEFT]

    @property
    def right(self) -> _ProviderSide:
        return self._sides[Side.RIGHT]


def main(args=None):
    rclpy.init(args=args)
    node = SoftwareO10ProviderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
