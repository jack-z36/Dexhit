"""Pinocchio kinematic model construction for the O10 (BLOCKED_ENV).

Spec decision 20: Pinocchio loads the URDF with mimic explicitly disabled and
asserts ``nq == nv == 16``, retaining the full kinematic joint set. This is the
check that genuinely requires pinocchio to build the kinematic model.

pinocchio is NOT installed in the current environment and is NOT a declared
dependency of this package (ARCHITECTURE invariant A13 keeps numeric backends
behind adapters). The structural nq=nv=16 claim is therefore proven
separately and immediately in :mod:`omnihand_o10_model.urdf_validator` by
counting movable joints; the pinocchio-driven ``model.nq`` assertion below is
BLOCKED_ENV until pinocchio is available. It is not faked as a pass.

Missing dependency: ``pinocchio`` (``import pinocchio`` fails with
ModuleNotFoundError). Install e.g. via ``pip install pin\" \" --no-deps\" is not
sufficient; the project expects the conda/packaged ``pinocchio`` that ships the
Python bindings built against the URDF parser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from .contract import N_FULL, side_contract

#: Human-readable identifier of the missing environment dependency.
BLOCKED_ENV_DEPENDENCY = "pinocchio (python bindings, import pinocchio)"


class PinocchioUnavailableError(RuntimeError):
    """Raised when a pinocchio-dependent check cannot run (BLOCKED_ENV)."""


def is_pinocchio_available() -> bool:
    """Return True iff ``import pinocchio`` succeeds in the current process."""
    try:
        import pinocchio  # noqa: F401
    except Exception:
        return False
    return True


def _require_pinocchio():
    if not is_pinocchio_available():
        raise PinocchioUnavailableError(
            f"BLOCKED_ENV: {BLOCKED_ENV_DEPENDENCY} is not installed. Building the "
            f"{N_FULL}-dimensional O10 pinocchio model and asserting model.nq/nv "
            f"is blocked until it is available. The structural nq=nv={N_FULL} "
            f"check in omnihand_o10_model.urdf_validator does NOT require "
            f"pinocchio and is the current verification."
        )


@dataclass(frozen=True)
class PinocchioModelHandle:
    """Thin handle around a built pinocchio model (opaque to avoid leaking the
    pinocchio type into this module's import-time surface)."""

    nq: int
    nv: int
    side: str


def build_pinocchio_model(
    urdf_path: Union[str, os.PathLike],
    side: str,
) -> PinocchioModelHandle:
    """Build the O10 pinocchio model from a validated URDF with mimic disabled.

    BLOCKED_ENV: requires pinocchio. Raises
    :class:`PinocchioUnavailableError` when the dependency is missing rather
    than faking a pass.
    """
    _require_pinocchio()
    side_contract(side)  # validate side early
    import pinocchio

    urdf_path = Path(urdf_path)
    if not urdf_path.is_file():
        raise FileNotFoundError(f"URDF not found: {urdf_path}")
    # Build with mimic disabled: every URDF joint is retained as an independent
    # kinematic variable (decision 20). The palm is the model root, so no free
    # flyer is appended. The exact pinocchio call signature can vary by version;
    # the contract below (nq == nv == 16) is what must hold regardless.
    model = pinocchio.buildModelFromUrdf(str(urdf_path))
    if model.nq != N_FULL or model.nv != N_FULL:
        raise AssertionError(
            f"pinocchio O10 model dimension mismatch for side {side!r}: "
            f"expected nq=nv={N_FULL}, got nq={model.nq} nv={model.nv}"
        )
    return PinocchioModelHandle(nq=model.nq, nv=model.nv, side=side)
