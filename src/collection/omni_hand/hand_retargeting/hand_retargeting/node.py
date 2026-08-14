"""Thin ROS composition root for the T05 hand-retargeting slice."""

from __future__ import annotations

import math

from omnihand_o10_contracts import Side
from omnihand_o10_contracts.joints import ACTIVE_JOINT_NAMES
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from rokoko_omnihand_msgs.msg import RawHandFrame, RetargetingState
from sensor_msgs.msg import JointState

from .adapters.model_geometry import (
    load_robot_geometry,
    load_runtime_assets,
)
from .adapters.nlopt import NloptSlsqpOptimizer, NLoptUnavailableError
from .adapters.pinocchio import load_pinocchio_kinematics, PinocchioUnavailableError
from .application.session import RetargetingSession
from .contracts import RawHandFrameValue, RetargetingConfig
from .core.coupling import CouplingModel


_PHASE_VALUES = {
    "initializing": RetargetingState.PHASE_INITIALIZING,
    "collecting-lengths": RetargetingState.PHASE_COLLECTING_LENGTHS,
    "waiting-first-valid-ik": RetargetingState.PHASE_WAITING_FIRST_VALID_IK,
    "tracking": RetargetingState.PHASE_TRACKING,
    "stale": RetargetingState.PHASE_STALE,
    "recovery-confirming": RetargetingState.PHASE_RECOVERY_CONFIRMING,
    "recovery-resuming": RetargetingState.PHASE_RECOVERY_RESUMING,
    "model-error": RetargetingState.PHASE_MODEL_ERROR,
}
_IK_VALUES = {
    "uninitialized": RetargetingState.IK_UNINITIALIZED,
    "valid": RetargetingState.IK_VALID,
    "input-invalid": RetargetingState.IK_INPUT_INVALID,
    "side-invalid": RetargetingState.IK_SIDE_INVALID,
    "residual-exceeded": RetargetingState.IK_RESIDUAL_EXCEEDED,
    "solver-error": RetargetingState.IK_SOLVER_ERROR,
    "not-run-length-collecting": RetargetingState.IK_NOT_RUN_LENGTH_COLLECTING,
    "not-run-stale": RetargetingState.IK_NOT_RUN_STALE,
}
_LENGTH_VALUES = {
    "collecting": RetargetingState.LENGTH_COLLECTING,
    "frozen": RetargetingState.LENGTH_FROZEN,
    "current-invalid": RetargetingState.LENGTH_CURRENT_INVALID,
}


def _wire_solver_not_run() -> int:
    """
    Resolve the message's no-run code without duplicating its number.

    The current source message defines the code in its field defaults but does
    not expose a ``SOLVER_NOT_RUN`` constant.  Reading that generated default
    is safe at this adapter boundary and keeps the pure layer independent of
    ROS.  Future generated messages can provide the named constant directly.
    """
    named_value = getattr(RetargetingState, "SOLVER_NOT_RUN", None)
    if named_value is not None:
        return int(named_value)
    defaults = RetargetingState().solver_result_code
    if len(defaults) == 0:
        raise RuntimeError("RetargetingState has no solver_result_code field")
    return int(defaults[0])


_SOLVER_NOT_RUN = _wire_solver_not_run()


def _required(description: str) -> ParameterDescriptor:
    return ParameterDescriptor(description=description, dynamic_typing=True)


class HandRetargetingNode(Node):
    """Normalize each RawHandFrame side and publish event-driven diagnostics."""

    def __init__(self, **kwargs) -> None:
        super().__init__("hand_retargeting", **kwargs)
        config = self._load_required_config()
        self._sessions: dict[Side, RetargetingSession] = {}
        self._model_errors: dict[Side, str] = {}
        for side in Side:
            try:
                geometry = load_robot_geometry(side.value)
                try:
                    assets = load_runtime_assets(side.value)
                    kinematics = load_pinocchio_kinematics(assets, side.value)
                    coupling = CouplingModel.from_mjcf(assets.coupling_model)
                    optimizer = NloptSlsqpOptimizer(
                        coupling, kinematics, config.ik_max_evaluations, config.ik_max_time_sec
                    )
                    self._sessions[side] = RetargetingSession(
                        side, config, geometry, coupling=coupling,
                        kinematics=kinematics, optimizer=optimizer,
                    )
                except (PinocchioUnavailableError, NLoptUnavailableError) as error:
                    # Keep the T05 diagnostic path importable in a numeric-
                    # backend-free environment, but never claim IK success or
                    # publish commands. Production startup still logs the
                    # explicit BLOCKED_ENV reason.
                    self.get_logger().error(str(error))
                    self._sessions[side] = RetargetingSession(side, config, geometry)
            except Exception as error:
                self._model_errors[side] = str(error)
                self.get_logger().error(str(error))

        raw_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        state_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._state_publishers = {
            side: self.create_publisher(
                RetargetingState, f"/hand_retargeting/{side.value}/state", state_qos
            )
            for side in Side
        }
        self._command_publishers = {
            side: self.create_publisher(JointState, f"/o10_control/{side.value}/command", 10)
            for side in Side
        }
        self._subscriptions = [
            self.create_subscription(
                RawHandFrame,
                f"/rokoko/{side.value}/raw_hand",
                lambda message, selected=side: self._on_raw(selected, message),
                raw_qos,
            )
            for side in Side
        ]
        self._stale_timer = self.create_timer(0.05, self._check_stale)
        for side in Side:
            if side in self._model_errors:
                self._publish_state(side, self._decision_with_phase(
                    self._initial_decision(side), "model-error"
                ))
            else:
                self._publish_state(side, self._initial_decision(side))

    def _load_required_config(self) -> RetargetingConfig:
        names = {
            "palm_y_epsilon": "minimum valid palm longitudinal norm",
            "palm_x_epsilon": "minimum valid orthogonalized palm transverse norm",
            "finger_length_epsilon": "minimum valid human finger chain length",
            "length_window_size": "valid samples per length stability window",
            "stable_window_count": "consecutive stable windows before freezing",
            "length_nmad_thresholds": "five per-finger normalized MAD thresholds",
            "frozen_length_relative_thresholds": "five frozen-length deviation thresholds",
            "ik_residual_thresholds": "five per-finger normalized IK residual thresholds",
            "ik_max_evaluations": "maximum NLopt evaluations per finger",
            "ik_max_time_sec": "maximum NLopt time per finger in seconds",
            "smooth_time_constants": "ten active-joint receive-time low-pass constants",
            "stale_timeout_sec": "raw receive timeout before stale",
            "recovery_min_valid_frames": "minimum continuous full-side recovery frames",
            "recovery_min_duration_sec": "minimum recovery observation span in seconds",
        }
        values = {}
        missing = []
        for name, description in names.items():
            value = self.declare_parameter(name, descriptor=_required(description)).value
            if value is None:
                missing.append(name)
            values[name] = value
        if missing:
            raise ValueError(
                "required experimental parameters are missing: " + ", ".join(missing)
            )
        return RetargetingConfig(**values)

    @staticmethod
    def _initial_decision(side: Side):
        """Return the no-input snapshot used during model initialization."""
        from .contracts import RetargetingDecision

        return RetargetingDecision(
            phase="initializing",
            side_valid=False,
            all_lengths_frozen=False,
            command_published=False,
            length_frozen=(False,) * 5,
            length_current_valid=(False,) * 5,
            targets=None,
            input_stamp_ns=0,
            ik_state=("uninitialized",) * 5,
            has_valid_ik=(False,) * 5,
            used_previous_valid_target=(False,) * 5,
            residual_available=(False,) * 5,
            normalized_residual=(math.nan,) * 5,
            solver_result_code=(None,) * 5,
            solver_evaluations=(0,) * 5,
        )

    @staticmethod
    def _decision_with_phase(decision, phase: str, input_stamp_ns: int = 0):
        """Copy a pure snapshot while changing only its lifecycle phase."""
        return decision.__class__(
            phase=phase,
            side_valid=decision.side_valid,
            all_lengths_frozen=decision.all_lengths_frozen,
            command_published=decision.command_published,
            length_frozen=decision.length_frozen,
            length_current_valid=decision.length_current_valid,
            targets=decision.targets,
            input_stamp_ns=input_stamp_ns,
            ik_state=decision.ik_state,
            has_valid_ik=decision.has_valid_ik,
            used_previous_valid_target=decision.used_previous_valid_target,
            residual_available=decision.residual_available,
            normalized_residual=decision.normalized_residual,
            solver_result_code=decision.solver_result_code,
            solver_evaluations=decision.solver_evaluations,
            solve_executed=decision.solve_executed,
            command_stamp_ns=decision.command_stamp_ns,
        )

    def _on_raw(self, side: Side, message: RawHandFrame) -> None:
        if side in self._model_errors:
            self._publish_model_error(side, message)
            return
        frame = RawHandFrameValue(
            node_names=tuple(message.node_names),
            positions=tuple((point.x, point.y, point.z) for point in message.positions),
            received_at_ns=Time.from_msg(message.header.stamp).nanoseconds,
        )
        try:
            decision = self._sessions[side].process(frame)
        except ValueError as error:
            self.get_logger().warning(f"dropped invalid {side.value} RawHandFrame: {error}")
            return

        self._publish_state(side, decision)
        if decision.command_published and decision.command_positions is not None:
            command = JointState()
            command.header.stamp = message.header.stamp
            command.name = list(ACTIVE_JOINT_NAMES)
            command.position = list(decision.command_positions)
            # velocity and effort remain empty by contract.
            self._command_publishers[side].publish(command)

    def _check_stale(self) -> None:
        now_ns = self.get_clock().now().nanoseconds
        for side, session in self._sessions.items():
            decision = session.check_stale(now_ns)
            if decision is not None:
                self._publish_state(side, decision)

    def _publish_state(self, side: Side, decision) -> None:
        """Convert one pure decision to the sole RetargetingState wire schema."""
        state = RetargetingState()
        state.header.stamp = self.get_clock().now().to_msg()
        state.header.frame_id = ""
        state.side = side.value
        if decision.input_stamp_ns:
            state.input_stamp = Time(nanoseconds=decision.input_stamp_ns).to_msg()
        state.solve_executed = decision.solve_executed
        if decision.solve_executed:
            state.solve_finished_stamp = Time(
                nanoseconds=(
                    decision.solve_finished_at_ns
                    or Time.from_msg(state.header.stamp).nanoseconds
                )
            ).to_msg()
            state.solve_duration_sec = decision.solve_duration_sec
        else:
            state.solve_duration_sec = math.nan
        state.phase = _PHASE_VALUES.get(decision.phase, RetargetingState.PHASE_MODEL_ERROR)
        state.ready = all(decision.has_valid_ik) and decision.all_lengths_frozen
        state.stale = decision.stale or state.phase in (
            RetargetingState.PHASE_STALE,
            RetargetingState.PHASE_RECOVERY_CONFIRMING,
            RetargetingState.PHASE_RECOVERY_RESUMING,
        )
        state.command_published = decision.command_published
        state.length_state = [
            _LENGTH_VALUES["frozen"]
            if frozen and current_valid
            else _LENGTH_VALUES["current-invalid"]
            if frozen
            else _LENGTH_VALUES["collecting"]
            for frozen, current_valid in zip(
                decision.length_frozen, decision.length_current_valid
            )
        ]
        state.ik_state = [_IK_VALUES[value] for value in decision.ik_state]
        state.has_valid_ik = list(decision.has_valid_ik)
        state.used_previous_valid_target = list(decision.used_previous_valid_target)
        state.residual_available = list(decision.residual_available)
        state.normalized_residual = list(decision.normalized_residual)
        state.solver_result_code = [
            _SOLVER_NOT_RUN if value is None else value
            for value in decision.solver_result_code
        ]
        state.solver_evaluations = list(decision.solver_evaluations)
        state.recovery_valid_count = decision.recovery_valid_count
        state.recovery_valid_duration_sec = decision.recovery_valid_duration_sec
        self._state_publishers[side].publish(state)

    def _publish_model_error(self, side: Side, raw: RawHandFrame) -> None:
        self.get_logger().error(
            f"cannot process {side.value} RawHandFrame while model is unavailable"
        )
        decision = self._decision_with_phase(
            self._initial_decision(side),
            "model-error",
            Time.from_msg(raw.header.stamp).nanoseconds,
        )
        self._publish_state(side, decision)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = HandRetargetingNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
