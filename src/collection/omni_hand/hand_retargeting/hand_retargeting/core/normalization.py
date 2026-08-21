"""Pure anatomical palm-frame and scale-normalization calculations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from omnihand_o10_contracts import Side

from ..contracts import Matrix3, NODE_SUFFIXES, RawHandFrameValue, RetargetingConfig, Vector3


class InvalidPalmFrame(ValueError):
    """The current side cannot define a finite anatomical palm frame."""


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(value: float, vector: Vector3) -> Vector3:
    return (value * vector[0], value * vector[1], value * vector[2])


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(vector: Vector3) -> float:
    return math.sqrt(_dot(vector, vector))


def _unit(vector: Vector3, epsilon: float, label: str) -> Vector3:
    length = _norm(vector)
    if not math.isfinite(length) or length <= epsilon:
        raise InvalidPalmFrame(f"{label} is degenerate")
    return _scale(1.0 / length, vector)


def _finite_vector(vector: Vector3) -> bool:
    return len(vector) == 3 and all(math.isfinite(value) for value in vector)


@dataclass(frozen=True)
class PalmFrame:
    origin: Vector3
    axes: Matrix3

    def from_world(self, point: Vector3) -> Vector3:
        relative = _sub(point, self.origin)
        x_axis, y_axis, z_axis = self.axes
        return (_dot(x_axis, relative), _dot(y_axis, relative), _dot(z_axis, relative))


@dataclass(frozen=True)
class RobotHandGeometry:
    """Geometry derived by the model Adapter from one locked per-side URDF."""

    finger_roots: tuple[Vector3, ...]
    finger_chain_lengths: tuple[float, ...]
    direction_mapping: Matrix3

    def __post_init__(self) -> None:
        if len(self.finger_roots) != 5 or len(self.finger_chain_lengths) != 5:
            raise ValueError("robot geometry must contain five fingers")
        if not all(_finite_vector(root) for root in self.finger_roots):
            raise ValueError("robot finger roots must be finite 3-vectors")
        if not all(math.isfinite(value) and value > 0.0 for value in self.finger_chain_lengths):
            raise ValueError("robot finger-chain lengths must be positive and finite")
        if len(self.direction_mapping) != 3 or not all(
            _finite_vector(row) for row in self.direction_mapping
        ):
            raise ValueError("direction mapping must be a finite 3x3 matrix")
        rows = self.direction_mapping
        for index, row in enumerate(rows):
            if not math.isclose(_dot(row, row), 1.0, abs_tol=1e-8):
                raise ValueError("direction mapping must be orthonormal")
            for other in rows[index + 1:]:
                if not math.isclose(_dot(row, other), 0.0, abs_tol=1e-8):
                    raise ValueError("direction mapping must be orthonormal")
        if not math.isclose(_dot(_cross(rows[0], rows[1]), rows[2]), 1.0, abs_tol=1e-8):
            raise ValueError("direction mapping must have determinant +1")

    def map_vector(self, vector: Vector3) -> Vector3:
        return tuple(
            _dot(row, vector) for row in self.direction_mapping
        )  # type: ignore[return-value]


def validate_frame(frame: RawHandFrameValue, side: Side) -> None:
    expected = tuple(side.value + suffix for suffix in NODE_SUFFIXES)
    if frame.node_names != expected or len(frame.positions) != 21:
        raise ValueError("RawHandFrame does not match the canonical 21-node order")
    if isinstance(frame.received_at_ns, bool) or not isinstance(frame.received_at_ns, int):
        raise ValueError("received_at_ns must be an integer")


def build_palm_frame(
    positions: tuple[Vector3, ...],
    side: Side,
    config: RetargetingConfig,
) -> PalmFrame:
    required = (0, 5, 9, 13, 17)
    if any(not _finite_vector(positions[index]) for index in required):
        raise InvalidPalmFrame("palm construction position is non-finite")
    origin = positions[0]
    center = _scale(
        0.25,
        tuple(
            sum(positions[index][axis] for index in required[1:])
            for axis in range(3)
        ),
    )
    y_axis = _unit(_sub(center, origin), config.palm_y_epsilon, "palm longitudinal axis")
    raw_x = (
        _sub(positions[5], positions[17])
        if side is Side.RIGHT
        # Both sides use anatomical +X from little-finger root to index root.
        else _sub(positions[5], positions[17])
    )
    orthogonal_x = _sub(raw_x, _scale(_dot(raw_x, y_axis), y_axis))
    x_axis = _unit(orthogonal_x, config.palm_x_epsilon, "palm transverse axis")
    z_axis = _cross(x_axis, y_axis)
    if not all(_finite_vector(axis) for axis in (x_axis, y_axis, z_axis)):
        raise InvalidPalmFrame("palm frame is non-finite")
    return PalmFrame(origin, (x_axis, y_axis, z_axis))


def finger_positions_in_palm(
    frame: RawHandFrameValue,
    palm: PalmFrame,
) -> tuple[tuple[Vector3, ...], ...]:
    result = []
    for finger_index in range(5):
        start = 1 + finger_index * 4
        result.append(tuple(palm.from_world(point) for point in frame.positions[start:start + 4]))
    return tuple(result)


def finger_chain_length(points: tuple[Vector3, ...], epsilon: float) -> float | None:
    if len(points) != 4 or any(not _finite_vector(point) for point in points):
        return None
    length = sum(_norm(_sub(points[index + 1], points[index])) for index in range(3))
    return length if math.isfinite(length) and length > epsilon else None


def normalized_mad(samples: tuple[float, ...]) -> tuple[float, float]:
    center = float(median(samples))
    dispersion = float(median(tuple(abs(sample - center) for sample in samples))) / center
    return center, dispersion
