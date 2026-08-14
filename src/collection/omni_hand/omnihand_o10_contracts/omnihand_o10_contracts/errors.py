"""Typed contract errors.

Value-object construction either succeeds with a fully validated immutable
object or fails by raising one of these typed errors. Rejection is always
explicit; the package never silently coerces, clamps or drops invalid input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoids a circular import with .side; Side is annotation-only here
    from .side import Side

__all__ = [
    "O10ContractError",
    "InvalidSideError",
    "InvalidJointVectorError",
    "InvalidSampleTimeError",
]


class O10ContractError(ValueError):
    """Base class for every rejection raised by omnihand_o10_contracts."""


class InvalidSideError(O10ContractError):
    """Raised when a value does not resolve to a known logical hand Side."""


class InvalidJointVectorError(O10ContractError):
    """Raised when a 10-vector is the wrong dimension, non-finite or out of limits.

    Attributes:
        side: The logical side the vector was intended for, when known.
        reason: Machine-stable short code describing the failure class.
        index: The offending component index when the failure is localised.
        value: The offending component value when the failure is localised.
    """

    def __init__(
        self,
        message: str,
        *,
        side: Optional[Side] = None,
        reason: str = "invalid",
        index: Optional[int] = None,
        value: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.side = side
        self.reason = reason
        self.index = index
        self.value = value


class InvalidSampleTimeError(O10ContractError):
    """Raised when a sample time is negative, non-finite or otherwise invalid."""
