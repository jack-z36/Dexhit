"""Public-graph tests for the O10 control node ``sides`` selection parameter.

The default value must reproduce the historical both-sides wiring byte for
byte; selecting one side must wire only that side's endpoints, and an invalid
value must fail construction instead of silently starting a half graph.
"""

import pytest
import rclpy

from omnihand_o10_contracts import Side

from omnihand_o10_control.node import O10ControlNode

from test_o10_control_node import make_config


def _overrides(value: str | None):
    from rclpy.parameter import Parameter

    if value is None:
        return None
    return [Parameter(name="sides", value=value)]


def _build(selected: str | None):
    kwargs = {}
    if selected != "right":
        kwargs["left_config"] = make_config(Side.LEFT)
    kwargs["right_config"] = make_config(Side.RIGHT)
    kwargs["parameter_overrides"] = _overrides(selected)
    return O10ControlNode(**kwargs)


@pytest.fixture
def ros(request):
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


_LEFT_COMMAND = "/o10_control/left/command"
_RIGHT_COMMAND = "/o10_control/right/command"


@pytest.mark.parametrize("ros", [None], indirect=True)
def test_default_construction_keeps_both_side_endpoints(ros):
    control = _build(None)
    other = rclpy.create_node("side_selection_observer")
    try:
        assert other.count_subscribers(_LEFT_COMMAND) == 1
        assert other.count_subscribers(_RIGHT_COMMAND) == 1
        assert other.count_publishers("/o10/left/joint_cmd") == 1
        assert other.count_publishers("/o10/right/joint_cmd") == 1
    finally:
        other.destroy_node()
        control.destroy_node()


@pytest.mark.parametrize("ros", ["left"], indirect=True)
def test_sides_left_wires_only_the_left_side(ros):
    control = _build("left")
    other = rclpy.create_node("side_selection_observer")
    try:
        assert other.count_subscribers(_LEFT_COMMAND) == 1
        assert other.count_subscribers(_RIGHT_COMMAND) == 0
        assert other.count_publishers("/o10/left/joint_cmd") == 1
        assert other.count_publishers("/o10/right/joint_cmd") == 0
    finally:
        other.destroy_node()
        control.destroy_node()


@pytest.mark.parametrize("ros", ["right"], indirect=True)
def test_sides_right_wires_only_the_right_side(ros):
    control = _build("right")
    other = rclpy.create_node("side_selection_observer")
    try:
        assert other.count_subscribers(_LEFT_COMMAND) == 0
        assert other.count_subscribers(_RIGHT_COMMAND) == 1
        service_names = dict(
            other.get_service_names_and_types_by_node("o10_control_node", "/")
        )
        assert "/o10_control/right/clear_fault" in service_names
        assert "/o10_control/left/clear_fault" not in service_names
    finally:
        other.destroy_node()
        control.destroy_node()


@pytest.mark.parametrize(
    "ros",
    ["center"],
    indirect=True,
    ids=["invalid-sides-value"],
)
def test_invalid_sides_value_fails_construction(ros):
    with pytest.raises(ValueError, match="sides"):
        O10ControlNode(
            left_config=make_config(Side.LEFT),
            right_config=make_config(Side.RIGHT),
            parameter_overrides=_overrides("center"),
        )
