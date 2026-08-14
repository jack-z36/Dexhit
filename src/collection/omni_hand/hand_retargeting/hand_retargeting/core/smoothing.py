"""Receive-time based first-order soft joint smoothing."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass
class LowPassFilter:
    time_constants: tuple[float, ...]
    value: np.ndarray | None = None
    last_stamp_ns: int | None = None

    def update(self, target: np.ndarray, received_at_ns: int) -> np.ndarray | None:
        target = np.asarray(target, dtype=np.float64)
        if target.shape != (10,) or not np.all(np.isfinite(target)):
            return None
        if self.value is None:
            self.value = target.copy()
            self.last_stamp_ns = received_at_ns
            return self.value.copy()
        if self.last_stamp_ns is None or not isinstance(received_at_ns, int):
            return None
        dt = (received_at_ns - self.last_stamp_ns) / 1_000_000_000.0
        if not math.isfinite(dt) or dt <= 0.0:
            return None
        alpha = 1.0 - np.exp(-dt / np.asarray(self.time_constants, dtype=np.float64))
        self.value = self.value + alpha * (target - self.value)
        self.last_stamp_ns = received_at_ns
        return self.value.copy()

    def hold(self) -> np.ndarray | None:
        return None if self.value is None else self.value.copy()

    def reset_time(self, received_at_ns: int) -> None:
        self.last_stamp_ns = received_at_ns
