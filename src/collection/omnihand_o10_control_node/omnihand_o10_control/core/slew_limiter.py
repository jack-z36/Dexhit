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
    "project_slew",
]


class SlewUnavailableError(ValueError):
    """No validated base exists yet (limiter not feedback-initialised)."""


class SlewTimeError(ValueError):
    """The monotonic time interval is not finite and positive."""


class SlewResultError(ValueError):
    """The clipped output is not finite or leaves the per-side joint limits."""


def project_slew(
    *,
    side: Side | str,
    base_position,
    base_monotonic: float,
    soft_position,
    monotonic_now: float,
    max_rates: tuple[float, ...],
    max_time_credit: float,
    compare_epsilon: tuple[float, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """Project one soft target from an explicit running-state base."""

    selected_side = Side.from_value(side)
    limits = JOINT_LIMITS[selected_side]
    base = np.asarray(base_position, dtype=np.float64)
    soft = np.asarray(soft_position, dtype=np.float64)
    rates = np.asarray(max_rates, dtype=np.float64)
    epsilon = np.asarray(compare_epsilon, dtype=np.float64)
    expected = (ACTIVE_JOINT_COUNT,)
    if base.shape != expected or not limits.contains(base):
        raise SlewUnavailableError(
            f"{selected_side.value} slew base is not a valid in-limit vector"
        )
    if soft.shape != expected or not limits.contains(soft):
        raise SlewResultError(
            f"{selected_side.value} soft target is not a valid in-limit vector"
        )
    if rates.shape != expected or not np.all(np.isfinite(rates)):
        raise SlewResultError("max_rates must be a finite 10-dimensional vector")
    if epsilon.shape != expected or not np.all(np.isfinite(epsilon)):
        raise SlewResultError(
            "compare_epsilon must be a finite 10-dimensional vector"
        )

    dt = float(monotonic_now) - float(base_monotonic)
    if not np.isfinite(dt) or dt <= 0.0:
        raise SlewTimeError(
            f"{selected_side.value} slew time interval is not finite and positive: {dt!r}"
        )
    credit = min(dt, float(max_time_credit))
    step = rates * credit
    command = base + np.clip(soft - base, -step, +step)
    command = np.clip(command, limits.lower, limits.upper)
    if not np.all(np.isfinite(command)) or not limits.contains(command):
        raise SlewResultError(
            f"{selected_side.value} slew output is not finite and in limits"
        )
    return command, np.abs(command - soft) > epsilon


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
        return project_slew(
            side=self.side,
            base_position=self._base,
            base_monotonic=self._base_monotonic,
            soft_position=soft_position,
            monotonic_now=monotonic_now,
            max_rates=tuple(float(value) for value in self._max_rates),
            max_time_credit=self._max_credit,
            compare_epsilon=compare_epsilon,
        )

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
