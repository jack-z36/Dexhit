"""ROS 2 node that runs the pure O10 control sessions against the wire.

The node is the only place that touches rclpy entities and the wire schema
(ARCHITECTURE A03).  It owns:

* effect execution -- publish commands / control state / error queries, call the
  read-active-joints service, and respond to operator services;
* the asynchronous read-future tracking; and
* the blocking clear_fault round-trips (error-status query then feedback read),
  performed synchronously in the service handler with a ``MultiThreadedExecutor``
  so the provider callbacks keep running while the handler waits.

All state-machine decisions stay inside :class:`ControlSession`; the node never
decides phase, fault, or result codes.
"""

from __future__ import annotations

import threading
import time

import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from rokoko_omnihand_msgs.msg import O10ControlState
from rokoko_omnihand_msgs.srv import ControlOperation, ReadO10ActiveJoints
from sensor_msgs.msg import JointState
from std_msgs.msg import Empty, Int16MultiArray

from omnihand_o10_contracts import JointFeedback, JointSampleTime, Side

from .adapters.ros_convert import (
    build_command_message,
    build_state_message,
    error_words_to_joint_error,
    joint_state_to_soft_target,
    operation_result_to_response,
    read_response_to_feedback,
    ros_time_to_sample_time,
)
from .application.control_session import ControlSession
from .contracts import (
    CommandPublishFailed,
    CommandSent,
    ErrorStatusReceived,
    FeedbackReceived,
    InvalidErrorStatusReceived,
    InvalidFeedbackReceived,
    OperationResult,
    OperatorClearFaultRequest,
    PublishControlState,
    QueryErrorStatus,
    ReadActiveJointsResult,
    ReadActiveJointsTimeout,
    RequestActiveJointsRead,
    SendJointCommand,
    TargetReceived,
    TimeoutCheck,
)

__all__ = ["O10ControlNode", "main"]


def _config_from_params(node: Node, side: Side) -> dict:
    prefix = f"{side.value}"
    import inspect

    from omnihand_o10_control.contracts import ControlConfig

    fields = [f.name for f in inspect.signature(ControlConfig).parameters.values()]
    values = {}
    for field in fields:
        if field == "side":
            values[field] = side
            continue
        param_name = f"{prefix}.{field}"
        if not node.has_parameter(param_name):
            node.declare_parameter(param_name)
        value = node.get_parameter(param_name).value
        if value is None:
            raise ValueError(f"required O10 control parameter is missing: {param_name}")
        values[field] = value
    return values


class _SideRuntime:
    """Wiring for one logical hand side."""

    def __init__(
        self,
        node: Node,
        side: Side,
        config,
        io_group,
    ):
        self.side = side
        self.config = config
        self.session = ControlSession(config)

        self.command_pub = node.create_publisher(
            JointState, f"/o10/{side.value}/joint_cmd", 10
        )
        self.state_pub = node.create_publisher(
            O10ControlState, f"/o10_control/{side.value}/state", 10
        )
        self.error_cmd_pub = node.create_publisher(
            Empty, f"/o10/{side.value}/joint_error_cmd", 10
        )
        self.command_sub = node.create_subscription(
            JointState,
            f"/o10_control/{side.value}/command",
            lambda message: node._on_command(side, message),
            10,
            callback_group=io_group,
        )
        self.feedback_sub = node.create_subscription(
            JointState,
            f"/o10/{side.value}/joint_states",
            lambda message: node._on_joint_states(side, message),
            10,
            callback_group=io_group,
        )
        self.error_sub = node.create_subscription(
            Int16MultiArray,
            f"/o10/{side.value}/joint_error_states",
            lambda message: node._on_joint_error_states(side, message),
            10,
            callback_group=io_group,
        )
        self.read_client = node.create_client(
            ReadO10ActiveJoints,
            f"/o10/{side.value}/read_active_joints",
            callback_group=io_group,
        )

        self.pending_read_future = None
        self.pending_read_deadline: float | None = None

        self.error_lock = threading.Lock()
        self.error_seq = 0
        self.error_payload: tuple[int, ...] | None = None


class O10ControlNode(Node):
    """Run the two per-side O10 control sessions against the wire graph."""

    def __init__(self, left_config=None, right_config=None):
        super().__init__("o10_control_node")
        # I/O (subscriptions, timer, read client) and operator services live in
        # SEPARATE mutually-exclusive groups: the blocking clear_fault handler
        # must not stall the feedback / error-status subscriptions it waits on.
        self._io_group = MutuallyExclusiveCallbackGroup()
        self._service_group = MutuallyExclusiveCallbackGroup()
        self._left = self._build_side(Side.LEFT, left_config)
        self._right = self._build_side(Side.RIGHT, right_config)
        self._sides = {Side.LEFT: self._left, Side.RIGHT: self._right}

        self._build_services(self._left, "clear_fault")
        self._build_services(self._right, "clear_fault")

        for side in (Side.LEFT, Side.RIGHT):
            self._publish_state(side, self._sides[side].session.initial_snapshot(self._ros_now()))

        self._timer = self.create_timer(
            self._sides[Side.LEFT].config.control_check_period,
            self._on_timer,
            callback_group=self._io_group,
        )

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_side(self, side: Side, override) -> _SideRuntime:
        if override is not None:
            config = override
        else:
            from omnihand_o10_control.contracts import ControlConfig

            config = ControlConfig(**_config_from_params(self, side))
        return _SideRuntime(self, side, config, self._io_group)

    def _build_services(self, runtime: _SideRuntime, operation: str) -> None:
        node = self
        self.create_service(
            ControlOperation,
            f"/o10_control/{runtime.side.value}/{operation}",
            lambda request, response, r=runtime, op=operation: self._on_operation(
                r, op, request, response
            ),
            callback_group=self._service_group,
        )

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

    def _ros_now(self) -> JointSampleTime:
        return JointSampleTime(self.get_clock().now().nanoseconds * 1e-9)

    def _mono_now(self) -> float:
        return time.monotonic()

    def _stamp_now(self):
        return self.get_clock().now().to_msg()

    # ------------------------------------------------------------------
    # Subscription callbacks (non-blocking entry points)
    # ------------------------------------------------------------------

    def _on_command(self, side: Side, message: JointState) -> None:
        runtime = self._sides[side]
        received_at = self._ros_now()
        value = joint_state_to_soft_target(side, message, received_at)
        effects = runtime.session.on_target(
            TargetReceived(value, received_at, self._mono_now(), received_at)
        )
        self._apply_effects(runtime, effects, response=None)

    def _on_joint_states(self, side: Side, message: JointState) -> None:
        runtime = self._sides[side]
        ros_now = self._ros_now()
        mono_now = self._mono_now()
        try:
            feedback = JointFeedback(
                side=side,
                values=tuple(float(value) for value in message.position),
                stamp=ros_time_to_sample_time(message.header.stamp),
            )
        except (TypeError, ValueError) as error:
            effects = runtime.session.on_invalid_feedback(
                InvalidFeedbackReceived(side, str(error), ros_now, mono_now)
            )
        else:
            effects = runtime.session.on_feedback(
                FeedbackReceived(feedback, ros_now, mono_now)
            )
        self._apply_effects(runtime, effects, response=None)

    def _on_joint_error_states(self, side: Side, message: Int16MultiArray) -> None:
        runtime = self._sides[side]
        ros_now = self._ros_now()
        mono_now = self._mono_now()
        with runtime.error_lock:
            try:
                payload = tuple(int(value) & 0xFFFF for value in message.data)
                runtime.error_payload = (
                    payload if len(payload) == 10 else None
                )
            except (TypeError, ValueError):
                runtime.error_payload = None
            runtime.error_seq += 1

        if runtime.session.clear_fault_in_progress:
            return
        try:
            error = error_words_to_joint_error(side, message, ros_now)
        except ValueError as error:
            effects = runtime.session.on_invalid_error_status(
                InvalidErrorStatusReceived(
                    side, str(error), ros_now, mono_now
                )
            )
        else:
            effects = runtime.session.on_error_status(
                ErrorStatusReceived(error, ros_now, mono_now)
            )
        self._apply_effects(runtime, effects, response=None)

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------

    def _on_operation(self, runtime: _SideRuntime, operation: str, request, response):
        ros_now = self._ros_now()
        effects = runtime.session.on_clear_fault_request(
            OperatorClearFaultRequest(self._mono_now(), ros_now)
        )
        self._apply_effects(runtime, effects, response=response)
        return response

    # ------------------------------------------------------------------
    # Timer (periodic control check + read-future reaping)
    # ------------------------------------------------------------------

    def _on_timer(self) -> None:
        for side in (Side.LEFT, Side.RIGHT):
            runtime = self._sides[side]
            effects = runtime.session.check_timeouts(
                TimeoutCheck(self._mono_now(), self._ros_now())
            )
            self._apply_effects(runtime, effects, response=None)
            self._reap_read_future(runtime)

    def _reap_read_future(self, runtime: _SideRuntime) -> None:
        future = runtime.pending_read_future
        if future is None:
            return
        mono_now = self._mono_now()
        ros_now = self._ros_now()
        if future.done():
            runtime.pending_read_future = None
            try:
                result = future.result()
            except Exception:
                result = None
            feedback = (
                read_response_to_feedback(runtime.side, result)
                if result is not None
                else None
            )
            effects = runtime.session.on_read_result(
                ReadActiveJointsResult(
                    feedback is not None,
                    feedback,
                    ros_now,
                    mono_now,
                )
            )
            self._apply_effects(runtime, effects, response=None)
        elif (
            runtime.pending_read_deadline is not None
            and mono_now > runtime.pending_read_deadline
        ):
            runtime.pending_read_future = None
            effects = runtime.session.on_read_timeout(
                ReadActiveJointsTimeout(mono_now)
            )
            self._apply_effects(runtime, effects, response=None)

    # ------------------------------------------------------------------
    # Effect execution
    # ------------------------------------------------------------------

    def _apply_effects(
        self, runtime: _SideRuntime, effects, response
    ) -> None:
        for effect in effects:
            if isinstance(effect, PublishControlState):
                self._publish_state(runtime.side, effect.state)
            elif isinstance(effect, SendJointCommand):
                self._send_command(runtime, effect)
            elif isinstance(effect, QueryErrorStatus):
                if response is not None:
                    self._clear_fault_error_query(runtime, response)
                else:
                    runtime.error_cmd_pub.publish(Empty())
            elif isinstance(effect, RequestActiveJointsRead):
                if response is not None:
                    self._clear_fault_read(runtime, response)
                else:
                    self._start_read(runtime)
            elif isinstance(effect, OperationResult):
                if response is not None:
                    self._fill_response(response, effect)

    def _send_command(self, runtime: _SideRuntime, effect: SendJointCommand) -> None:
        message = build_command_message(effect.command)
        ros_now = self._ros_now()
        try:
            runtime.command_pub.publish(message)
        except Exception:
            effects = runtime.session.on_command_publish_failed(
                CommandPublishFailed(ros_now, self._mono_now())
            )
        else:
            effects = runtime.session.on_command_sent(
                CommandSent(effect.command, ros_now, self._mono_now())
            )
        self._apply_effects(runtime, effects, response=None)

    def _publish_state(self, side: Side, state) -> None:
        self._sides[side].state_pub.publish(
            build_state_message(state, self._stamp_now())
        )

    def _fill_response(self, response, result: OperationResult) -> None:
        message = build_state_message(result.state, self._stamp_now())
        filled = operation_result_to_response(result, message)
        response.success = filled.success
        response.result_code = filled.result_code
        response.message = filled.message
        response.state = filled.state

    # ------------------------------------------------------------------
    # Async read (normal initialisation)
    # ------------------------------------------------------------------

    def _start_read(self, runtime: _SideRuntime) -> None:
        if (
            runtime.pending_read_future is not None
            and not runtime.pending_read_future.done()
        ):
            return
        if not runtime.read_client.service_is_ready():
            return
        request = ReadO10ActiveJoints.Request()
        runtime.pending_read_future = runtime.read_client.call_async(request)
        runtime.pending_read_deadline = (
            self._mono_now() + runtime.config.read_service_timeout
        )

    # ------------------------------------------------------------------
    # Blocking clear_fault round-trips (service-handler context only)
    # ------------------------------------------------------------------

    def _clear_fault_error_query(self, runtime: _SideRuntime, response) -> None:
        timeout = runtime.config.clear_fault_error_timeout
        with runtime.error_lock:
            seq0 = runtime.error_seq
        runtime.error_cmd_pub.publish(Empty())
        ok, bits = self._wait_error_status(runtime, seq0, timeout)
        effects = runtime.session.on_clear_fault_error_query(
            ok, bits, self._mono_now(), self._ros_now()
        )
        self._apply_effects(runtime, effects, response=response)

    def _wait_error_status(
        self, runtime: _SideRuntime, seq0: int, timeout: float
    ) -> tuple[bool, tuple[int, ...] | None]:
        with runtime.error_lock:
            seq0 = runtime.error_seq
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with runtime.error_lock:
                if runtime.error_seq > seq0:
                    return True, runtime.error_payload
            time.sleep(0.001)
        return False, None

    def _clear_fault_read(self, runtime: _SideRuntime, response) -> None:
        timeout = runtime.config.clear_fault_read_timeout
        completed, feedback = self._blocking_read(runtime, timeout)
        effects = runtime.session.on_clear_fault_read(
            completed, feedback, self._mono_now(), self._ros_now()
        )
        self._apply_effects(runtime, effects, response=response)

    def _blocking_read(
        self, runtime: _SideRuntime, timeout: float
    ) -> tuple[bool, JointFeedback | None]:
        if not runtime.read_client.service_is_ready():
            return False, None
        request = ReadO10ActiveJoints.Request()
        future = runtime.read_client.call_async(request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not future.done():
            time.sleep(0.001)
        if not future.done():
            return False, None
        try:
            result = future.result()
        except Exception:
            return False, None
        if result is None or not result.success:
            return False, None
        return True, read_response_to_feedback(runtime.side, result)


def main(args=None):
    """Run the O10 control node with a multi-threaded executor."""
    rclpy.init(args=args)
    node = O10ControlNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()
