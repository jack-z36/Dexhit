from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from omnihand_o10_contracts import JointSampleTime, JointTarget, Side
from omnihand_o10_hardware_adapter.backends import AgilinkO10Backend
from omnihand_o10_hardware_adapter.contracts import BackendCode


@dataclass
class FakeErrorReport:
    stalled: bool = False
    overheat: bool = False
    over_current: bool = False
    motor_except: bool = False
    commu_except: bool = False


class FakeAgilinkHand:
    def __init__(self, positions, errors):
        self.positions = list(positions)
        self.errors = list(errors)
        self.commands = []
        self.position_reads = 0
        self.error_reads = 0

    def set_all_active_joint_angles(self, angles):
        self.commands.append(list(angles))

    def get_all_active_joint_angles(self):
        self.position_reads += 1
        return list(self.positions.pop(0))

    def get_all_error_reports(self):
        self.error_reads += 1
        return list(self.errors)


def test_agilink_backend_maps_command_feedback_errors_and_fresh_active_reads():
    side = Side.RIGHT
    first = (0.0,) * 10
    second = (0.01,) + (0.0,) * 9
    errors = [FakeErrorReport() for _ in range(10)]
    errors[2].over_current = True
    hand = FakeAgilinkHand([first, second, second], errors)
    clock_values = iter((10.0, 11.0, 12.0, 13.0))
    backend = AgilinkO10Backend(side, hand, clock=lambda: next(clock_values))

    command = JointTarget(side, first, JointSampleTime(1.0))
    command_result = backend.send_command(command)
    feedback_result = backend.read_feedback()
    error_result = backend.query_errors()
    first_read = backend.read_active_joints()
    second_read = backend.read_active_joints()

    assert command_result.code is BackendCode.SUCCESS
    assert hand.commands == [list(first)]
    assert feedback_result.value.as_tuple() == first
    assert error_result.value.as_tuple() == (0, 0, 4, 0, 0, 0, 0, 0, 0, 0)
    assert first_read.value.as_tuple() == second
    assert second_read.value.as_tuple() == second
    assert first_read.value.stamp == JointSampleTime(12.0)
    assert second_read.value.stamp == JointSampleTime(13.0)
    assert hand.position_reads == 3
    assert hand.error_reads == 1


def test_agilink_backend_does_not_turn_malformed_sdk_results_into_success():
    hand = FakeAgilinkHand([(0.0,) * 9], [FakeErrorReport() for _ in range(10)])
    backend = AgilinkO10Backend(Side.LEFT, hand, clock=lambda: 1.0)

    result = backend.read_active_joints()

    assert result.code is BackendCode.INVALID_RESULT
    assert not result.success
    assert result.value is None


def test_agilink_backend_requires_explicit_connection_fields():
    try:
        AgilinkO10Backend.connection_kwargs(
            transport="zlgcan",
            hand_device_id=1,
            canfd_device_id=None,
            canfd_channel_id=0,
        )
    except ValueError as error:
        assert "canfd_device_id" in str(error)
    else:
        raise AssertionError("missing transport configuration must be rejected")


@pytest.mark.parametrize(
    ("transport", "factory", "extra"),
    [
        (
            "zlgcan",
            "create_hand_by_zlgcan",
            {"canfd_device_id": 2, "canfd_channel_id": 3},
        ),
        (
            "hcan",
            "create_hand_by_hcan",
            {"canfd_device_id": 2, "canfd_channel_id": 3},
        ),
        ("rs485", "create_hand_by_rs485", {"uart_port": "/dev/ttyFAKE"}),
        ("usb", "create_hand_by_usb", {"uart_port": "/dev/ttyFAKE"}),
        (
            "socketcan",
            "create_hand_socketcan",
            {"can_interface": "can-fake"},
        ),
        (
            "zlgcan_tcp",
            "create_hand_by_zlgcan_tcp",
            {"host": "127.0.0.1", "port": 8000, "canfd_channel_id": 4},
        ),
    ],
)
def test_from_sdk_uses_official_factory_kwargs(monkeypatch, transport, factory, extra):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(init=lambda: True)

    sdk_class = type("OmniHand2025", (), {factory: staticmethod(create)})
    sdk_module = SimpleNamespace(
        HandType=SimpleNamespace(LEFT="LEFT", RIGHT="RIGHT"),
        OmniHand2025=sdk_class,
    )
    monkeypatch.setitem(__import__("sys").modules, "omnihand", sdk_module)

    AgilinkO10Backend.from_sdk(
        Side.LEFT,
        transport=transport,
        hand_device_id=7,
        **extra,
    )

    assert calls == [{"hand_type": "LEFT", "hand_device_id": 7, **extra}]


def test_from_sdk_fails_explicitly_when_sdk_is_missing(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "omnihand", None)

    with pytest.raises(RuntimeError, match="SDK wheel is not installed"):
        AgilinkO10Backend.from_sdk(
            Side.LEFT,
            transport="rs485",
            hand_device_id=1,
            uart_port="/dev/ttyFAKE",
        )


def test_from_sdk_fails_explicitly_when_factory_cannot_construct(monkeypatch):
    sdk_class = type(
        "OmniHand2025",
        (),
        {
            "create_hand_by_rs485": staticmethod(
                lambda **kwargs: (_ for _ in ()).throw(RuntimeError("fake construction failure"))
            )
        },
    )
    sdk_module = SimpleNamespace(
        HandType=SimpleNamespace(LEFT="LEFT", RIGHT="RIGHT"),
        OmniHand2025=sdk_class,
    )
    monkeypatch.setitem(__import__("sys").modules, "omnihand", sdk_module)

    with pytest.raises(RuntimeError, match="failed to construct"):
        AgilinkO10Backend.from_sdk(
            Side.LEFT,
            transport="rs485",
            hand_device_id=1,
            uart_port="/dev/ttyFAKE",
        )
