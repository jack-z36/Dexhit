"""Pure per-side final hard slew limiter (Spec decision 40; ADR-0003).

The limiter owns two immutable run facts:

* ``base_position`` -- the last actually-sent command (initialised from a fresh
  real feedback read, never from zero / mid-range / first target / cache);
* ``base_monotonic`` -- the monotonic instant associated with that base.

``limit`` computes a clipped command WITHOUT mutating state; the Application
advances the base only after the runtime reports a successful publish
(``confirm``).  Invalid updates never advance the base (Spec decision 41).
"""

from __future__ import annotations

from omnihand_o10_contracts import ACTIVE_JOINT_COUNT, JOINT_LIMITS, Side

import numpy as np

__all__ = [
    "SlewLimiter",
    "SlewUnavailableError",
    "SlewTimeError",
    "SlewResultError",
]


class SlewUnavailableError(ValueError):
    """No validated base exists yet (limiter not feedback-initialised)."""


class SlewTimeError(ValueError):
    """The monotonic time interval is not finite and positive."""


class SlewResultError(ValueError):
    """The clipped output is not finite or leaves the per-side joint limits."""


class SlewLimiter:
    """Final per-joint command change-rate limiter for one logical side."""

    def __init__(
        self,
        side: Side | str,
        max_rates: tuple[float, ...],
        max_time_credit: float,
    ) -> None:
        self.side = Side.from_value(side)
        self._max_rates = np.asarray(max_rates, dtype=np.float64)
        if self._max_rates.shape != (ACTIVE_JOINT_COUNT,):
            raise ValueError(
                f"max_rates must be {ACTIVE_JOINT_COUNT}-dimensional, "
                f"got shape {self._max_rates.shape}"
            )
        self._max_credit = float(max_time_credit)
        self._base: np.ndarray | None = None
        self._base_monotonic: float | None = None

    @property
    def initialized(self) -> bool:
        """True once a validated real-feedback base has been accepted."""
        return self._base is not None and self._base_monotonic is not None

    @property
    def base_position(self) -> tuple[float, ...] | None:
        if self._base is None:
            return None
        return tuple(float(value) for value in self._base)

    @property
    def base_monotonic(self) -> float | None:
        return self._base_monotonic

    def initialize(self, position, monotonic_now: float) -> None:
        """Adopt a freshly read real joint position as the base.

        Does not validate finiteness/limits here because the caller must hand
        in an already-validated :class:`JointFeedback`; a plain vector is
        accepted for convenience and defensively validated anyway.
        """
        values = np.asarray(position, dtype=np.float64)
        limits = JOINT_LIMITS[self.side]
        if not limits.contains(values):
            raise ValueError(
                f"{self.side.value} slew base is not a valid 10-dim in-limit "
                "joint vector"
            )
        self._base = values.copy()
        self._base.flags.writeable = False
        self._base_monotonic = monotonic_now

    def clear_time_credit(self) -> None:
        """Discard the accumulated time credit (disarm; Spec decision 47)."""
        self._base_monotonic = None

    def rebase_clock(self, monotonic_now: float) -> None:
        """Restart the monotonic origin without changing the position base."""
        if self._base is None:
            raise SlewUnavailableError("cannot rebase an uninitialised limiter")
        self._base_monotonic = monotonic_now

    def limit(
        self,
        soft_position,
        monotonic_now: float,
        compare_epsilon: tuple[float, ...],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(command, slew_limited)`` without mutating the base.

        ``command`` is base + clip(soft - base, -rate*credit, +rate*credit)
        with ``credit = min(dt, max_time_credit)``.  ``slew_limited[j]`` is
        true where ``|command[j] - soft[j]| > epsilon[j]``.
        """
        if self._base is None or self._base_monotonic is None:
            raise SlewUnavailableError(
                f"{self.side.value} slew limiter is not feedback-initialised"
            )
        dt = monotonic_now - self._base_monotonic
        if not np.isfinite(dt) or dt <= 0.0:
            raise SlewTimeError(
                f"{self.side.value} slew time interval is not finite and "
                f"positive: {dt!r}"
            )
        credit = min(dt, self._max_credit)
        soft = np.asarray(soft_position, dtype=np.float64)
        delta = soft - self._base
        step = self._max_rates * credit
        command = self._base + np.clip(delta, -step, +step)

        limits = JOINT_LIMITS[self.side]
        # Clamp to the inclusive joint limits instead of faulting: a soft
        # target sitting exactly on a limit plus one ulp of floating-point
        # rounding (``base + (limit - base)`` can land 1 ulp outside) used to
        # raise SlewResultError and latch SAFETY_INVARIANT every time the
        # operator drove a joint to its limit. The physical joint stops at its
        # limit, so the command must stop there too.
        command = np.clip(command, limits.lower, limits.upper)

        if not np.all(np.isfinite(command)):
            raise SlewResultError(
                f"{self.side.value} slew output is not finite"
            )
        if not limits.contains(command):
            raise SlewResultError(
                f"{self.side.value} slew output leaves the joint limits"
            )

        epsilon = np.asarray(compare_epsilon, dtype=np.float64)
        flags = np.abs(command - soft) > epsilon
        return command, flags

    def confirm(self, position, monotonic_now: float) -> None:
        """Advance the base to the successfully published command."""
        values = np.asarray(position, dtype=np.float64)
        limits = JOINT_LIMITS[self.side]
        if not limits.contains(values):
            raise SlewResultError(
                f"{self.side.value} cannot confirm an out-of-limits command"
            )
        self._base = values.copy()
        self._base.flags.writeable = False
        self._base_monotonic = monotonic_now
