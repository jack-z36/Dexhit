from __future__ import annotations

from pathlib import Path

import pytest

from omnihand_o10_contracts import Side
from omnihand_o10_hardware_adapter.composition import build_production_applications


def _parameters(**overrides):
    values = {}
    for side in ("left", "right"):
        prefix = f"o10.{side}."
        values.update(
            {
                f"{prefix}transport": "zlgcan",
                f"{prefix}hand_device_id": 1,
                f"{prefix}canfd_device_id": 0,
                f"{prefix}canfd_channel_id": 0,
            }
        )
    values.update(overrides)
    return values


def test_production_composition_rejects_missing_transport_before_sdk_access():
    with pytest.raises(RuntimeError, match="o10.left.transport"):
        build_production_applications({})


def test_production_composition_constructs_both_sides_with_explicit_parameters():
    calls = []

    def factory(side, **kwargs):
        calls.append((side, kwargs))
        return object()

    applications = build_production_applications(
        _parameters(),
        backend_factory=factory,
    )

    assert set(applications) == {Side.LEFT, Side.RIGHT}
    assert calls == [
        (
            Side.LEFT,
            {
                "transport": "zlgcan",
                "hand_device_id": 1,
                "canfd_device_id": 0,
                "canfd_channel_id": 0,
            },
        ),
        (
            Side.RIGHT,
            {
                "transport": "zlgcan",
                "hand_device_id": 1,
                "canfd_device_id": 0,
                "canfd_channel_id": 0,
            },
        ),
    ]


def test_production_composition_fails_when_sdk_construction_fails():
    def failing_factory(side, **kwargs):
        raise RuntimeError("SDK wheel is not installed")

    with pytest.raises(RuntimeError, match="left.*SDK wheel is not installed"):
        build_production_applications(
            _parameters(),
            backend_factory=failing_factory,
        )


def test_node_default_path_uses_production_composition():
    node_source = (Path(__file__).resolve().parents[1] / "omnihand_o10_hardware_adapter" / "node.py").read_text(
        encoding="utf-8"
    )

    assert "if applications is None:" in node_source
    assert "build_production_applications(parameters)" in node_source
    assert "BlockedExternalBackend" not in node_source
