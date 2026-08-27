"""Pure results shared by the production Provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

__all__ = ["BackendCode", "BLOCKED_EXTERNAL", "HardwareResponse"]


class BackendCode(StrEnum):
    """Machine-readable outcomes at the external hardware boundary."""

    SUCCESS = "SUCCESS"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
    HARDWARE_ERROR = "HARDWARE_ERROR"
    INVALID_RESULT = "INVALID_RESULT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


BLOCKED_EXTERNAL = BackendCode.BLOCKED_EXTERNAL

T = TypeVar("T")


@dataclass(frozen=True)
class HardwareResponse(Generic[T]):
    """A result that never hides an unavailable external capability."""

    code: BackendCode
    message: str
    value: T | None = None

    @property
    def success(self) -> bool:
        """Whether the operation completed with a usable value."""

        return self.code is BackendCode.SUCCESS

    @classmethod
    def success_result(cls, value: T | None = None, message: str = "success"):
        """Build a successful result for a completed operation."""

        return cls(BackendCode.SUCCESS, message, value)

    @classmethod
    def failure(cls, code: BackendCode, message: str):
        """Build an explicit non-success result without a stale value."""

        if code is BackendCode.SUCCESS:
            raise ValueError("failure result cannot use SUCCESS")
        return cls(code, message, None)
