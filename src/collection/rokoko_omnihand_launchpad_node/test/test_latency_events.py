from pathlib import Path

from rokoko_omnihand_launchpad.latency_events import (
    CHAIN,
    TOPICS,
    LatencyEventsStore,
    read_events,
)


def ros_stamp(value):
    return {"sec": int(value), "nanosec": int((value % 1) * 1e9)}


def message(value, **fields):
    result = {"header": {"stamp": ros_stamp(value)}}
    result.update(fields)
    return result


def test_latency_is_derived_from_injected_public_timestamps_and_missing_is_null():
    store = LatencyEventsStore(sides=("left",), clock=lambda: 10.0)
    side = "left"
    store.observe(TOPICS["raw_hand"].format(side=side), message(1.0, source_timestamp=1234.5), received_at=1.1)
    store.observe(TOPICS["retargeting_state"].format(side=side), message(1.2, input_stamp=ros_stamp(1.15), solve_finished_stamp=ros_stamp(1.18)), received_at=1.2)
    store.observe(TOPICS["command"].format(side=side), message(1.25), received_at=1.25)
    store.observe(TOPICS["joint_cmd"].format(side=side), message(1.30), received_at=1.3)
    store.observe(TOPICS["joint_states"].format(side=side), message(1.38), received_at=1.38)

    result = store.snapshot(now=1.4)["sides"][side]
    assert result["timestamps"]["source_timestamp"] == 1234.5
    assert result["hops"][0]["latency_ms"] is None  # source epoch is explicitly unconfirmed
    assert result["hops"][1]["latency_ms"] == 150.0
    assert result["hops"][2]["latency_ms"] == 30.0
    assert result["hops"][-1]["latency_ms"] == 80.0
    assert result["hops"][0]["available"] is False


def test_topic_frequency_uses_receive_times_without_synthetic_samples():
    store = LatencyEventsStore(sides=("left",))
    topic = TOPICS["raw_hand"].format(side="left")
    for now in (0.0, 0.1, 0.2):
        store.observe(topic, {}, received_at=now)
    rate = store.snapshot(now=0.2)["sides"]["left"]["rates"]["raw_hand"]
    assert rate["frequency_hz"] == 10.0
    assert rate["samples"] == 3


def test_fault_view_matches_control_state_bits_and_events_preserve_jsonl_order(tmp_path: Path):
    store = LatencyEventsStore(sides=("left",))
    store.observe(TOPICS["control_state"].format(side="left"), {
        "fault_latched": True, "fault_reason_mask": 16,
    }, received_at=2.0)
    fault = store.snapshot(now=2.1)["sides"]["left"]["fault"]
    assert fault == {"fault_latched": True, "fault_reason_mask": 16, "available": True}

    run = tmp_path / "run"
    run.mkdir()
    (run / "events.jsonl").write_text(
        '{"timestamp":"1","type":"run_created"}\n'
        '{"timestamp":"2","type":"web_mark","label":"fault"}\n',
        encoding="utf-8",
    )
    assert [item["type"] for item in read_events(run)] == ["run_created", "web_mark"]


def test_chain_contract_is_explicit():
    assert CHAIN == ("source_timestamp", "receive", "input", "solve", "command", "joint_cmd", "joint_states")
