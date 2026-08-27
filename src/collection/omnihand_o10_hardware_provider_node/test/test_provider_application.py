from __future__ import annotations

from dataclasses import dataclass, field

from omnihand_o10_contracts import JointError, JointFeedback, JointSampleTime, JointTarget, Side
from omnihand_o10_hardware_adapter.application.provider import (
    O10HardwareProviderApplication,
)
from omnihand_o10_hardware_adapter.contracts import (
    BLOCKED_EXTERNAL,
    BackendCode,
    HardwareResponse,
)


@dataclass
class FakeBackend:
    feedback: JointFeedback
    errors: JointError
    active_positions: list[JointFeedback]
    commands: list[JointTarget] = field(default_factory=list)
    feedback_reads: int = 0
    error_queries: int = 0
    active_reads: int = 0

    def send_command(self, command: JointTarget) -> HardwareResponse[None]:
        self.commands.append(command)
        return HardwareResponse.success_result(message="command accepted")

    def read_feedback(self) -> HardwareResponse[JointFeedback]:
        self.feedback_reads += 1
        return HardwareResponse.success_result(self.feedback, "feedback read")

    def query_errors(self) -> HardwareResponse[JointError]:
        self.error_queries += 1
        return HardwareResponse.success_result(self.errors, "error query completed")

    def read_active_joints(self) -> HardwareResponse[JointFeedback]:
        self.active_reads += 1
        return HardwareResponse.success_result(
            self.active_positions.pop(0), "fresh active-joint read"
        )


def _feedback(side: Side, value: float, stamp: float) -> JointFeedback:
    values = [0.0] * 10
    values[0] = value
    return JointFeedback(side, values, JointSampleTime(stamp))


def _error(side: Side, value: int, stamp: float) -> JointError:
    return JointError(side, (value,) * 10, JointSampleTime(stamp))


def test_application_maps_command_feedback_and_error_query_to_backend():
    side = Side.RIGHT
    feedback = _feedback(side, 0.01, 1.0)
    errors = _error(side, 0, 2.0)
    backend = FakeBackend(feedback, errors, [_feedback(side, 0.2, 3.0)])
    application = O10HardwareProviderApplication(side, backend)
    command = JointTarget(side, (0.0,) * 10, JointSampleTime(4.0))

    assert application.send_command(command).code is BackendCode.SUCCESS
    assert application.read_feedback().value == feedback
    assert application.query_errors().value == errors
    assert backend.commands == [command]
    assert backend.feedback_reads == 1
    assert backend.error_queries == 1


def test_read_active_joints_triggers_a_new_backend_read_each_request():
    side = Side.LEFT
    first = _feedback(side, 0.01, 10.0)
    second = _feedback(side, 0.02, 11.0)
    backend = FakeBackend(first, _error(side, 0, 9.0), [first, second])
    application = O10HardwareProviderApplication(side, backend)

    first_result = application.read_active_joints()
    second_result = application.read_active_joints()

    assert backend.active_reads == 2
    assert first_result.value == first
    assert second_result.value == second
    assert first_result.value != second_result.value


def test_missing_backend_is_explicitly_blocked_external_for_every_operation():
    application = O10HardwareProviderApplication(Side.LEFT)
    command = JointTarget(Side.LEFT, (0.0,) * 10, JointSampleTime(1.0))

    results = (
        application.send_command(command),
        application.read_feedback(),
        application.query_errors(),
        application.read_active_joints(),
    )

    assert all(result.code is BLOCKED_EXTERNAL for result in results)
    assert all("SDK" in result.message or "external" in result.message.lower() for result in results)
