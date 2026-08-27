"""Pure Provider Application: delegate operations and validate returned values."""

from __future__ import annotations

from collections.abc import Callable

from omnihand_o10_contracts import JointError, JointFeedback, JointTarget, Side

from ..backends import BlockedExternalBackend
from ..contracts import BackendCode, HardwareResponse
from ..ports import O10HardwarePort

__all__ = ["O10HardwareProviderApplication"]


class O10HardwareProviderApplication:
    """Expose the four O10 capabilities without owning control state.

    The Application deliberately has no feedback, error, or active-joint
    cache.  ``read_active_joints`` invokes the selected Port on every call so
    the service request remains a fresh-read request rather than a cache read.
    """

    def __init__(self, side: Side | str, port: O10HardwarePort | None = None) -> None:
        self.side = Side.from_value(side)
        self._port = port if port is not None else BlockedExternalBackend(self.side)

    @property
    def port(self) -> O10HardwarePort:
        """Return the injected Port for composition and diagnostics."""

        return self._port

    def send_command(self, command: JointTarget) -> HardwareResponse[None]:
        """Delegate one final command and preserve the backend outcome."""

        if command.side is not self.side:
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"command side {command.side.value!r} does not match {self.side.value!r}",
            )
        return self._invoke("send_command", lambda: self._port.send_command(command))

    def read_feedback(self) -> HardwareResponse[JointFeedback]:
        """Delegate a feedback read and reject an invalid successful payload."""

        return self._read_value("read_feedback", JointFeedback, self._port.read_feedback)

    def query_errors(self) -> HardwareResponse[JointError]:
        """Delegate an active error query and reject an invalid payload."""

        return self._read_value("query_errors", JointError, self._port.query_errors)

    def read_active_joints(self) -> HardwareResponse[JointFeedback]:
        """Perform exactly one fresh active-joint read for this request."""

        return self._read_value(
            "read_active_joints", JointFeedback, self._port.read_active_joints
        )

    def _read_value(self, operation: str, expected_type, call: Callable):
        result = self._invoke(operation, call)
        if not result.success:
            return result
        if not isinstance(result.value, expected_type):
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"{operation} returned an unexpected value type",
            )
        if result.value.side is not self.side:
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"{operation} returned the wrong logical side",
            )
        return result

    @staticmethod
    def _invoke(self_operation: str, call: Callable):
        try:
            result = call()
        except Exception as error:  # boundary turns backend failures into data
            return HardwareResponse.failure(
                BackendCode.INTERNAL_ERROR,
                f"{self_operation} failed inside external boundary: {error}",
            )
        if not isinstance(result, HardwareResponse):
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"{self_operation} did not return HardwareResponse",
            )
        return result
