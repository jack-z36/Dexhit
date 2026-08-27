"""Deterministic JSON-v3 UDP source for Launchpad mock/data-link sessions.

The payload builder is deliberately owned by ``rokoko_omnihand_system_test``.
This module only chooses the side, schedules frames, and owns the UDP socket;
it does not decode or reimplement the Rokoko wire format.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path


def _scene_builder():
    """Load the public system-test fixture in an installed or source workspace."""
    try:
        from rokoko_omnihand_system_test.scenes import calibrated_scene_payload
    except ModuleNotFoundError:
        # A source checkout is useful before colcon has installed the explicit
        # mock dependency.  The production/real composition never imports this
        # module, so this fallback remains a mock-only source seam.
        package_source = (
            Path(__file__).resolve().parents[2]
            / "teleoperation_support"
            / "system_tests"
        )
        if not package_source.is_dir():
            raise
        sys.path.insert(0, str(package_source))
        from rokoko_omnihand_system_test.scenes import calibrated_scene_payload

    return calibrated_scene_payload


def payloads(*, side: str, count: int = 0) -> Iterator[bytes]:
    """Yield a deterministic sequence of calibrated JSON-v3 frames.

    ``count=0`` means continuous output.  A sequence starts at zero on every
    process invocation; wall-clock send time is not embedded in the payload.
    """
    if side not in {"both", "left", "right"}:
        raise ValueError("side must be one of both, left, right")
    builder = _scene_builder()
    left, right = side in {"both", "left"}, side in {"both", "right"}
    sequence = 0
    while count <= 0 or sequence < count:
        yield builder(sequence=sequence, left=left, right=right)
        sequence += 1


def send(
    *, host: str = "127.0.0.1", port: int = 14043, side: str = "both",
    fps: float = 30.0, count: int = 0, initial_delay: float = 0.0,
) -> int:
    """Send the deterministic fixture until ``count`` frames or termination."""
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if fps <= 0:
        raise ValueError("fps must be greater than zero")
    if initial_delay > 0:
        time.sleep(initial_delay)
    interval = 1.0 / fps
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for frame in payloads(side=side, count=count):
            started = time.monotonic()
            sock.sendto(frame, (host, port))
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14043)
    parser.add_argument("--side", choices=("both", "left", "right"), default="both")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--initial-delay", type=float, default=0.0)
    args = parser.parse_args(argv)
    return send(**vars(args))


if __name__ == "__main__":
    raise SystemExit(main())
