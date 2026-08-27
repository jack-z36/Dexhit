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


def calibrated_scene_payload(
    *, sequence: int = 0, left: bool = True, right: bool = True,
    invalid_finger: int | None = None, degenerate_palm: bool = False,
) -> bytes:
    """Return a stable, non-degenerate public replay fixture.

    This is intentionally a synthetic test fixture, not a claim about Rokoko
    Studio output.  The wrist, four finger roots and each four-node chain are
    fixed in a non-collinear palm layout so normalization and length freezing
    can complete before the real ROS retargeting node is observed.
    """
    roots = (0.8, 0.6, 0.2, -0.2, -0.6)
    body: dict[str, dict] = {}
    for side, enabled, offset in (
        ("left", left, 0.0),
        ("right", right, 10.0),
    ):
        if not enabled:
            continue
        body[side + "Hand"] = _node((offset, 0.0, 0.0))
        for finger, root_x in enumerate(roots):
            if degenerate_palm:
                root_x = 0.0
            length = 1.2 if finger != invalid_finger else 2.4
            for joint, fraction in enumerate((0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)):
                body[side + NODE_SUFFIXES[1 + finger * 4 + joint]] = _node(
                    (offset + root_x, 1.0 + length * fraction, 0.02 * finger)
                )
    document = {
        "version": 3,
        "fps": 60,
        "scene": {
            "timestamp": 2000.0 + sequence / 60.0,
            "actors": [{"name": "T10CalibratedReplay", "body": body}],
        },
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")
