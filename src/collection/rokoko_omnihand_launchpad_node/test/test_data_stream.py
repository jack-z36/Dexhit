from __future__ import annotations

from rokoko_omnihand_launchpad.data_stream import (
    JOINT_CMD,
    JOINT_FEEDBACK,
    JOINT_TARGET,
    RETARGETING_STATE,
    DataStreamStore,
)


JOINTS = [f"joint_{index}" for index in range(10)]


def joint_message(offset: float) -> dict:
    return {"name": JOINTS, "position": [offset + index for index in range(10)]}


def test_injected_public_fields_are_preserved_for_joint_and_ik_panels():
    store = DataStreamStore(sides=("left",), sample_hz=10.0)
    store.observe(JOINT_TARGET.format(side="left"), joint_message(1.0), received_at=0.0)
    store.observe(JOINT_FEEDBACK.format(side="left"), joint_message(0.5), received_at=0.0)
    store.observe(JOINT_CMD.format(side="left"), joint_message(0.75), received_at=0.0)
    store.observe(RETARGETING_STATE.format(side="left"), {
        "phase": 3,
        "ik_state": [1, 1, 4, 1, 1],
        "normalized_residual": [0.01, 0.02, 0.225, float("nan"), 0.03],
        "residual_available": [True, True, True, False, True],
    }, received_at=0.0)

    side = store.snapshot()["sides"]["left"]
    assert side["joint_count"] == 10
    assert side["joint_names"] == JOINTS
    assert side["joints"]["target"][0]["values"]["joint_9"] == 10.0
    assert side["joints"]["feedback"][0]["values"]["joint_0"] == 0.5
    assert side["joints"]["joint_cmd"][0]["values"]["joint_0"] == 0.75
    assert side["states"][0]["phase"] == 3
    assert side["states"][0]["ik_state"] == [1, 1, 4, 1, 1]
    assert side["states"][0]["normalized_residual"] == [0.01, 0.02, 0.225, None, 0.03]


def test_each_stream_is_downsampled_to_about_ten_hz_without_fake_points():
    store = DataStreamStore(sides=("left",), sample_hz=10.0)
    topic = JOINT_TARGET.format(side="left")
    for index in range(26):
        store.observe(topic, joint_message(float(index)), received_at=index * 0.04)

    samples = store.snapshot()["sides"]["left"]["joints"]["target"]
    assert 8 <= len(samples) <= 11
    assert samples[0]["t"] == 0.0
    assert samples[-1]["t"] >= 0.8
    assert samples[-1]["values"]["joint_0"] >= 20.0


def test_unknown_topic_is_not_presented_as_live_data():
    store = DataStreamStore(sides=("left",))
    assert store.observe("/not/a/public/topic", joint_message(0), received_at=0.0) is False
    assert store.snapshot()["sides"]["left"]["states"] == []
