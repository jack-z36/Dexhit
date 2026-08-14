"""Small JSON-v3 scenes used by the public UDP system-test seam."""

from __future__ import annotations

import json


NODE_SUFFIXES = (
    "Hand",
    "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
    "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
    "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
    "RingProximal", "RingMedial", "RingDistal", "RingTip",
    "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
)


def _node(position: tuple[float, float, float]) -> dict:
    return {
        "position": {"x": position[0], "y": position[1], "z": position[2]},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    }


def scene_payload(*, sequence: int = 0, left: bool = True, right: bool = True) -> bytes:
    """Return a deterministic, valid JSON v3 UDP scene.

    The geometry is deliberately only a receiver fixture.  Robot-model validity
    belongs to the retargeting node and is observed through its state Topic.
    """
    body: dict[str, dict] = {}
    for side, enabled, offset in (
        ("left", left, 0.0),
        ("right", right, 100.0),
    ):
        if not enabled:
            continue
        for index, suffix in enumerate(NODE_SUFFIXES):
            body[side + suffix] = _node(
                (offset + float(index), 1.0 + float(index), 0.1 * sequence)
            )
    document = {
        "version": 3,
        "fps": 60,
        "scene": {
            "timestamp": 1000.0 + sequence / 60.0,
            "actors": [{"name": "T10FixtureActor", "body": body}],
        },
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")
