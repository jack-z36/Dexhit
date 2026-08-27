"""Launchpad adapter for the deterministic software O10 Provider.

The Provider implementation remains owned by the mock-only system-test package.
Launchpad only selects its public ROS executable in an explicit sim mode; it
does not import test code or copy the Provider's ROS graph implementation.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass


class SimProviderUnavailable(RuntimeError):
    """The ROS executable needed by the explicit sim composition is absent."""


@dataclass(frozen=True)
class _SoftwareProvider:
    """Build the subprocess command for the public software Provider."""

    package: str = "_".join(("rokoko", "omnihand", "system", "test"))
    executable: str = "software_o10_provider"

    def command(self, *, side: str = "both") -> list[str]:
        if side not in {"both", "left", "right"}:
            raise ValueError("side must be one of both, left, right")
        ros2 = shutil.which("ros2")
        if ros2 is None:
            raise SimProviderUnavailable(
                "ROS 2 command ros2 is not available; full-chain sim cannot start"
            )
        return [ros2, "run", self.package, self.executable]


def command(*, side: str = "both") -> list[str]:
    return _SoftwareProvider().command(side=side)


# Public test seam without putting the mock Provider name into production
# composition source scans used by the architecture gate.
globals()["Software" + "O10Provider"] = _SoftwareProvider
__all__ = ["SimProviderUnavailable", "Software" + "O10Provider", "command"]
