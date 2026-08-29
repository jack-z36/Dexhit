"""
Strict decoder for the confirmed Rokoko JSON v3 fields.

Rokoko Studio streams JSON v3 over UDP; the datagram is LZ4-frame-compressed
(magic ``04 22 4d 18``) when compression is enabled and plain JSON otherwise.
Both forms are accepted here.
"""

from dataclasses import dataclass
import json
import math
from typing import Literal, TypeAlias

import lz4.frame


Side: TypeAlias = Literal["left", "right"]
Vector3: TypeAlias = tuple[float, float, float]
Quaternion: TypeAlias = tuple[float, float, float, float]

_SEMANTIC_NODE_SUFFIXES = (
    "Hand",
    "ThumbProximal",
    "ThumbMedial",
    "ThumbDistal",
    "ThumbTip",
    "IndexProximal",
    "IndexMedial",
    "IndexDistal",
    "IndexTip",
    "MiddleProximal",
    "MiddleMedial",
    "MiddleDistal",
    "MiddleTip",
    "RingProximal",
    "RingMedial",
    "RingDistal",
    "RingTip",
    "LittleProximal",
    "LittleMedial",
    "LittleDistal",
    "LittleTip",
)

_LZ4_FRAME_MAGIC = b"\x04\x22\x4d\x18"


class _Pairs(list[tuple[str, object]]):
    """JSON object representation that retains duplicate member names."""


@dataclass(frozen=True)
class RawHandFrameValue:
    """A validated per-side frame, independent from ROS wire types."""

    actor_index: int
    actor_name: str
    source_timestamp: float
    received_at_ns: int
    node_names: tuple[str, ...]
    positions: tuple[Vector3, ...]
    orientations: tuple[Quaternion, ...]


@dataclass(frozen=True)
class DecodeResult:
    """
    Decoded frames plus explicit scene/per-side rejection diagnostics.

    ``actor_fallback`` is set to the actor index that was actually used when the
    configured ``actor_index`` was out of range but at least one actor was
    present (``actor_index`` auto-resolved to that fallback). It is ``None``
    when the requested index was used directly.
    """

    frames: dict[Side, RawHandFrameValue]
    side_rejections: dict[Side, str]
    scene_rejection: str | None = None
    actor_fallback: int | None = None


def _reject_scene(reason: str) -> DecodeResult:
    return DecodeResult({}, {}, reason)


def _decompress(payload: bytes) -> bytes:
    """Decompress an LZ4-framed payload; pass plain JSON through unchanged."""
    if not payload.startswith(_LZ4_FRAME_MAGIC):
        return payload
    try:
        return lz4.frame.decompress(payload)
    except RuntimeError as exc:
        raise ValueError(f"LZ4 decompression failed: {exc}") from exc


def _is_v3_version(value: object) -> bool:
    """
    Return True when value denotes Rokoko JSON v3.

    Rokoko emits the version as the string ``"3,0"``; the numeric ``3`` and
    the ``"3"``/``"3.0"`` spellings are also accepted as equivalent v3 marks.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 3
    if isinstance(value, str):
        major = value.strip().replace(",", ".").split(".")[0]
        return major == "3"
    return False


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, _Pairs):
        raise ValueError(f"{field} must be an object")
    result: dict[str, object] = {}
    for key, item in value:
        if key in result:
            raise ValueError(f"{field} contains duplicate member {key!r}")
        result[key] = item
    return result


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _components(value: object, names: tuple[str, ...], field: str) -> tuple[float, ...]:
    source = _object(value, field)
    return tuple(_finite_number(source.get(name), f"{field}.{name}") for name in names)


def _decode_side(
    body_pairs: _Pairs,
    side: Side,
    *,
    actor_index: int,
    actor_name: str,
    source_timestamp: float,
    received_at_ns: int,
    quaternion_norm_epsilon: float,
) -> RawHandFrameValue:
    prefix = side
    expected_names = tuple(prefix + suffix for suffix in _SEMANTIC_NODE_SUFFIXES)
    selected: dict[str, object] = {}
    expected = set(expected_names)
    for name, value in body_pairs:
        if name not in expected:
            continue
        if name in selected:
            raise ValueError(f"duplicate node {name!r}")
        selected[name] = value
    missing = [name for name in expected_names if name not in selected]
    if missing:
        raise ValueError(f"missing node {missing[0]!r}")

    positions: list[Vector3] = []
    orientations: list[Quaternion] = []
    for name in expected_names:
        node = _object(selected[name], name)
        position = _components(node.get("position"), ("x", "y", "z"), f"{name}.position")
        orientation = _components(
            node.get("rotation"), ("x", "y", "z", "w"), f"{name}.rotation"
        )
        norm = math.sqrt(sum(component * component for component in orientation))
        if norm <= quaternion_norm_epsilon:
            raise ValueError(f"{name}.rotation norm is too small")
        positions.append((position[0], position[1], position[2]))
        orientations.append(
            (orientation[0], orientation[1], orientation[2], orientation[3])
        )

    return RawHandFrameValue(
        actor_index=actor_index,
        actor_name=actor_name,
        source_timestamp=source_timestamp,
        received_at_ns=received_at_ns,
        node_names=expected_names,
        positions=tuple(positions),
        orientations=tuple(orientations),
    )


def decode_scene(
    payload: bytes,
    *,
    actor_index: int,
    received_at_ns: int,
    quaternion_norm_epsilon: float = 1e-12,
) -> DecodeResult:
    """Decode one datagram into independent, canonical left/right frames."""
    try:
        payload = _decompress(payload)
        root = json.loads(payload, object_pairs_hook=_Pairs)
        root_obj = _object(root, "root")
        version = root_obj.get("version")
        if not _is_v3_version(version):
            raise ValueError("version must be JSON v3")
        scene = _object(root_obj.get("scene"), "scene")
        source_timestamp = _finite_number(scene.get("timestamp"), "scene.timestamp")
        actors = scene.get("actors")
        if not isinstance(actors, list) or isinstance(actors, _Pairs):
            raise ValueError("scene.actors must be an array")
        if isinstance(actor_index, bool) or not isinstance(actor_index, int) or actor_index < 0:
            raise ValueError("actor_index must be a non-negative integer")
        if len(actors) == 0:
            raise ValueError(
                "configured actor does not exist (Rokoko scene has no actor)"
            )
        if actor_index >= len(actors):
            # Robustness: the configured index is out of range, but the scene
            # does carry at least one actor. Auto-resolve to the first available
            # actor so a lane that receives data is never dropped wholesale just
            # because the actor numbering moved. Decoding proceeds with index 0.
            actor_fallback = 0
            actor = _object(actors[actor_fallback], "scene.actors[0]")
        else:
            actor_fallback = None
            actor = _object(actors[actor_index], f"scene.actors[{actor_index}]")
        actor_name = actor.get("name")
        if not isinstance(actor_name, str):
            raise ValueError("actor.name must be a string")
        body = actor.get("body")
        if not isinstance(body, _Pairs):
            raise ValueError("actor.body must be an object")
        if isinstance(received_at_ns, bool) or not isinstance(received_at_ns, int):
            raise ValueError("received_at_ns must be an integer")
        epsilon = _finite_number(quaternion_norm_epsilon, "quaternion_norm_epsilon")
        if epsilon < 0.0:
            raise ValueError("quaternion_norm_epsilon must not be negative")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return _reject_scene(str(exc))

    effective_actor_index = 0 if actor_fallback is not None else actor_index
    frames: dict[Side, RawHandFrameValue] = {}
    side_rejections: dict[Side, str] = {}
    for side in ("left", "right"):
        try:
            frames[side] = _decode_side(
                body,
                side,
                actor_index=effective_actor_index,
                actor_name=actor_name,
                source_timestamp=source_timestamp,
                received_at_ns=received_at_ns,
                quaternion_norm_epsilon=epsilon,
            )
        except (ValueError, TypeError) as exc:
            side_rejections[side] = str(exc)
    return DecodeResult(frames, side_rejections, actor_fallback=actor_fallback)
