"""The pure logical hand Side.

``Side`` expresses only the logical ``left`` / ``right`` identity of a hand in
the control chain. It deliberately carries no device ID, CAN channel, USB path
or any ROS / hardware concept (CONTEXT.md glossary: 逻辑手侧). It is the
foundation of every per-side contract in this package.

ARCHITECTURE invariant A11 names ``omnihand_o10_contracts`` the single owner of
the logical-hand-side pure semantics; no other package may redefine it.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import InvalidSideError

__all__ = ["Side"]


class Side(StrEnum):
    """The logical hand side. Members compare equal to their string value."""

    LEFT = "left"
    RIGHT = "right"

    @classmethod
    def from_value(cls, value: "str | Side") -> "Side":
        """Resolve a Side from a string or pass through an existing member.

        Matching is case-insensitive on the canonical ``left``/``right``
        spellings (case is a presentation variant). Surrounding whitespace and
        any other spelling are rejected rather than silently coerced.
        """
        if isinstance(value, Side):
            return value
        if isinstance(value, str):
            candidate = value.lower()
            for member in cls:
                if member.value == candidate:
                    return member
        raise InvalidSideError(f"unsupported hand side: {value!r}")
