"""Behavior tests for the public pure scene-decoder seam."""

import json
from pathlib import Path

import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "official_fields_constructed_v3.json"


def _fixture_object():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _payload(scene):
    return json.dumps(scene, allow_nan=True).encode()


def test_complete_scene_is_reordered_without_changing_source_values():
    from rokoko_hand_receiver.core.decoder import decode_scene

    result = decode_scene(FIXTURE.read_bytes(), actor_index=0, received_at_ns=42)

    assert result.scene_rejection is None
    assert set(result.frames) == {"left", "right"}
    left = result.frames["left"]
    right = result.frames["right"]
    assert left.actor_index == right.actor_index == 0
    assert left.actor_name == right.actor_name == "DexhitFixtureActor"
    assert left.source_timestamp == right.source_timestamp == 1234.5
    assert left.received_at_ns == right.received_at_ns == 42
    assert left.node_names == (
        "leftHand",
        "leftThumbProximal", "leftThumbMedial", "leftThumbDistal", "leftThumbTip",
        "leftIndexProximal", "leftIndexMedial", "leftIndexDistal", "leftIndexTip",
        "leftMiddleProximal", "leftMiddleMedial", "leftMiddleDistal", "leftMiddleTip",
        "leftRingProximal", "leftRingMedial", "leftRingDistal", "leftRingTip",
        "leftLittleProximal", "leftLittleMedial", "leftLittleDistal", "leftLittleTip",
    )
    assert left.positions[6] == (6.0, 7.0, 8.0)
    assert left.orientations[6] == (0.0, 0.0, 0.0, 2.0)
    assert right.node_names[0] == "rightHand"
    assert right.node_names[-1] == "rightLittleTip"
    assert right.positions[-1] == (120.0, 121.0, 122.0)


@pytest.mark.parametrize(
    "payload, actor_index",
    [
        (b"not json", 0),
        (b'{"version":2,"scene":{"timestamp":1,"actors":[]}}', 0),
        (b'{"version":3,"scene":{"timestamp":NaN,"actors":[]}}', 0),
        (FIXTURE.read_bytes(), 1),
    ],
    ids=("invalid-json", "wrong-version", "invalid-source-time", "actor-absent"),
)
def test_scene_error_rejects_both_sides(payload, actor_index):
    from rokoko_hand_receiver.core.decoder import decode_scene

    result = decode_scene(payload, actor_index=actor_index, received_at_ns=42)

    assert result.frames == {}
    assert result.scene_rejection is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.pop("leftIndexTip"),
        lambda body: body["leftIndexTip"]["position"].update(x=float("nan")),
        lambda body: body["leftIndexTip"]["rotation"].update(w=0.0),
    ],
    ids=("missing-node", "non-finite-position", "zero-quaternion"),
)
def test_invalid_left_side_does_not_reject_valid_right_side(mutate):
    from rokoko_hand_receiver.core.decoder import decode_scene

    scene = _fixture_object()
    mutate(scene["scene"]["actors"][0]["body"])

    result = decode_scene(_payload(scene), actor_index=0, received_at_ns=42)

    assert set(result.frames) == {"right"}
    assert set(result.side_rejections) == {"left"}
    assert result.scene_rejection is None


def test_duplicate_left_node_does_not_reject_valid_right_side():
    from rokoko_hand_receiver.core.decoder import decode_scene

    payload = FIXTURE.read_bytes().replace(
        b'"leftIndexTip":',
        b'"leftIndexTipDuplicate": null, "leftIndexTip":',
        1,
    ).replace(
        b'"leftIndexTipDuplicate": null',
        b'"leftIndexTip": null',
        1,
    )

    result = decode_scene(payload, actor_index=0, received_at_ns=42)

    assert set(result.frames) == {"right"}
    assert "duplicate node" in result.side_rejections["left"]


def test_missing_right_side_publishes_only_left():
    from rokoko_hand_receiver.core.decoder import decode_scene

    scene = _fixture_object()
    body = scene["scene"]["actors"][0]["body"]
    scene["scene"]["actors"][0]["body"] = {
        name: value for name, value in body.items() if not name.startswith("right")
    }

    result = decode_scene(_payload(scene), actor_index=0, received_at_ns=42)

    assert set(result.frames) == {"left"}
    assert set(result.side_rejections) == {"right"}
