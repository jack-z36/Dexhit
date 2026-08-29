"""External O10 SDK adapter and the safe unavailable fallback."""

from __future__ import annotations

import time
from collections.abc import Callable

from omnihand_o10_contracts import JointError, JointFeedback, JointTarget, Side

from .contracts import BackendCode, HardwareResponse

__all__ = ["AgilinkO10Backend", "BlockedExternalBackend"]

_REQUEST_INTERVAL_RANGE = range(0, 101)


def _validated_request_interval(request_interval_ms: object) -> int | None:
    """Validate an explicit SDK-wide request interval (E5 diagnostic knob).

    ``None`` keeps the SDK untouched; otherwise the vendor documents integer
    milliseconds in 0..100 where 0 disables throttling entirely.
    """

    if request_interval_ms is None:
        return None
    if isinstance(request_interval_ms, bool) or not isinstance(request_interval_ms, int):
        raise ValueError(
            f"request_interval_ms must be None or an integer in "
            f"0..{_REQUEST_INTERVAL_RANGE.stop - 1}, got {request_interval_ms!r}"
        )
    if request_interval_ms not in _REQUEST_INTERVAL_RANGE:
        raise ValueError(
            f"request_interval_ms must be None or an integer in "
            f"0..{_REQUEST_INTERVAL_RANGE.stop - 1}, got {request_interval_ms!r}"
        )
    return request_interval_ms


class BlockedExternalBackend:
    """A safe construction default that cannot claim device access."""

    def __init__(self, side: Side) -> None:
        self.side = Side.from_value(side)

    def _blocked(self, operation: str):
        return HardwareResponse.failure(
            BackendCode.BLOCKED_EXTERNAL,
            f"{operation} BLOCKED_EXTERNAL: approved external hardware backend is unavailable",
        )

    def send_command(self, command: JointTarget) -> HardwareResponse[None]:
        return self._blocked("send_command")

    def read_feedback(self) -> HardwareResponse[JointFeedback]:
        return self._blocked("read_feedback")

    def query_errors(self) -> HardwareResponse[JointError]:
        return self._blocked("query_errors")

    def read_active_joints(self) -> HardwareResponse[JointFeedback]:
        return self._blocked("read_active_joints")


class AgilinkO10Backend:
    """Map the documented Agilink O10 Python SDK to :class:`O10HardwarePort`.

    The SDK object is injected after explicit, deployment-owned connection
    construction.  This keeps the external wheel out of the pure contracts and
    Application layers, and makes all reads direct SDK calls with no Provider
    cache.  ``from_sdk`` is the production composition helper; unit tests can
    inject a fake object exposing the same documented methods.
    """

    _ERROR_BITS = (
        ("stalled", 1 << 0),
        ("overheat", 1 << 1),
        ("over_current", 1 << 2),
        ("motor_except", 1 << 3),
        ("commu_except", 1 << 4),
    )

    def __init__(
        self,
        side: Side | str,
        hand: object,
        clock: Callable[[], float] = time.time,
        request_interval_ms: int | None = None,
    ) -> None:
        self.side = Side.from_value(side)
        self._hand = hand
        self._clock = clock
        interval = _validated_request_interval(request_interval_ms)
        if interval is not None:
            try:
                self._hand.set_request_interval(interval)
            except Exception as error:
                raise RuntimeError(
                    "Agilink O10 SDK failed to apply the global request "
                    f"interval {interval}: {error}"
                ) from error

    @classmethod
    def from_sdk(
        cls,
        side: Side | str,
        *,
        transport: str,
        hand_device_id: int,
        canfd_device_id: int | None = None,
        canfd_channel_id: int | None = None,
        can_interface: str | None = None,
        uart_port: str | None = None,
        host: str | None = None,
        port: int | None = None,
        request_interval_ms: int | None = None,
    ) -> "AgilinkO10Backend":
        """Construct and initialize one SDK hand from explicit connection data.

        ``request_interval_ms`` (E5 diagnostic knob) is forwarded to the
        backend constructor and applied to the initialized SDK hand; the
        default keeps the vendor configuration untouched.

        This method is intentionally lazy: importing the production Provider
        does not require the external wheel.  It must only be called by the
        production composition after all transport parameters are supplied.
        """

        connection = cls.connection_kwargs(
            transport=transport,
            hand_device_id=hand_device_id,
            canfd_device_id=canfd_device_id,
            canfd_channel_id=canfd_channel_id,
            can_interface=can_interface,
            uart_port=uart_port,
            host=host,
            port=port,
        )
        try:
            from omnihand import HandType, OmniHand2025
        except ImportError as error:
            raise RuntimeError("Agilink O10 SDK wheel is not installed") from error

        resolved_side = Side.from_value(side)
        connection["hand_type"] = HandType.LEFT if resolved_side is Side.LEFT else HandType.RIGHT
        factory = getattr(OmniHand2025, connection.pop("factory"))
        try:
            hand = factory(**connection)
        except Exception as error:
            raise RuntimeError("Agilink O10 SDK failed to construct the O10 hand") from error
        if hand is None:
            raise RuntimeError("Agilink O10 SDK could not create the O10 hand")
        try:
            initialized = hand.init()
        except Exception as error:
            raise RuntimeError("Agilink O10 SDK initialization raised an exception") from error
        if not initialized:
            raise RuntimeError("Agilink O10 SDK failed to initialize the O10 hand")
        return cls(resolved_side, hand, request_interval_ms=request_interval_ms)

    @staticmethod
    def connection_kwargs(
        *,
        transport: str,
        hand_device_id: int,
        canfd_device_id: int | None = None,
        canfd_channel_id: int | None = None,
        can_interface: str | None = None,
        uart_port: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> dict[str, object]:
        """Validate explicit SDK transport data and return vendor call kwargs."""

        if transport not in {
            "zlgcan",
            "hcan",
            "socketcan",
            "rs485",
            "usb",
            "zlgcan_tcp",
        }:
            raise ValueError(f"unsupported Agilink transport: {transport!r}")
        if not isinstance(hand_device_id, int) or not 0 < hand_device_id <= 255:
            raise ValueError("hand_device_id must be an explicit integer in 1..255")

        kwargs: dict[str, object] = {"hand_device_id": hand_device_id}
        if transport in {"zlgcan", "hcan"}:
            if not isinstance(canfd_device_id, int) or not 0 <= canfd_device_id <= 255:
                raise ValueError("canfd_device_id is required for CAN transport")
            if not isinstance(canfd_channel_id, int) or not 0 <= canfd_channel_id <= 255:
                raise ValueError("canfd_channel_id is required for CAN transport")
            kwargs.update(
                canfd_device_id=canfd_device_id,
                canfd_channel_id=canfd_channel_id,
            )
        elif transport == "socketcan":
            if not can_interface:
                raise ValueError("can_interface is required for SocketCAN transport")
            kwargs["can_interface"] = can_interface
        elif transport in {"rs485", "usb"}:
            if not uart_port:
                raise ValueError("uart_port is required for serial transport")
            kwargs["uart_port"] = uart_port
        elif transport == "zlgcan_tcp":
            if not host:
                raise ValueError("host is required for TCP transport")
            if not isinstance(port, int) or not 0 < port <= 65535:
                raise ValueError("port is required for TCP transport")
            if not isinstance(canfd_channel_id, int) or not 0 <= canfd_channel_id <= 255:
                raise ValueError("canfd_channel_id is required for TCP transport")
            kwargs.update(host=host, port=port, canfd_channel_id=canfd_channel_id)
        factory = "create_hand_socketcan" if transport == "socketcan" else f"create_hand_by_{transport}"
        kwargs["factory"] = factory
        return kwargs

    def send_command(self, command: JointTarget) -> HardwareResponse[None]:
        """Send one validated final position command through the SDK."""

        if command.side is not self.side:
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"command side {command.side.value!r} does not match {self.side.value!r}",
            )
        try:
            self._hand.set_all_active_joint_angles(list(command.as_tuple()))
        except Exception as error:
            return HardwareResponse.failure(BackendCode.HARDWARE_ERROR, f"send_command failed: {error}")
        return HardwareResponse.success_result(message="Agilink O10 command accepted")

    def read_feedback(self) -> HardwareResponse[JointFeedback]:
        """Read one current SDK position sample for command readback."""

        return self._read_positions("read_feedback")

    def query_errors(self) -> HardwareResponse[JointError]:
        """Trigger one SDK error-report query and map report flags to words.

        Uses the per-joint ``get_error_report(j)`` reader (joint index 1..10)
        instead of the batch ``get_all_error_reports()``: the vendor batch
        reader is documented as unstable on a healthy hand (intermittently
        returns 0 reports, and can magnify a single joint's commu_except into
        eight). A 0-report batch result makes the Provider publish nothing, the
        control error query times out, and the control session latches
        ERROR_MONITOR_TIMEOUT — freezing the hand mid-teleop. The per-joint
        reader has been verified stable on the real O10 hardware.
        """
        reports: list[object] = []
        try:
            for joint_index in range(1, 11):
                reports.append(self._hand.get_error_report(joint_index))
        except Exception as error:
            return HardwareResponse.failure(BackendCode.HARDWARE_ERROR, f"query_errors failed: {error}")
        if len(reports) != 10:
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"query_errors returned {len(reports)} reports; expected 10",
            )
        try:
            values = tuple(self._error_word(report) for report in reports)
            result = JointError(self.side, values, self._clock())
        except Exception as error:
            return HardwareResponse.failure(BackendCode.INVALID_RESULT, f"query_errors returned invalid reports: {error}")
        return HardwareResponse.success_result(result, "Agilink O10 error query completed")

    def read_active_joints(self) -> HardwareResponse[JointFeedback]:
        """Perform one new no-motion SDK active-joint read for each request."""

        return self._read_positions("read_active_joints")

    def _read_positions(self, operation: str) -> HardwareResponse[JointFeedback]:
        try:
            values = list(self._hand.get_all_active_joint_angles())
        except Exception as error:
            return HardwareResponse.failure(BackendCode.HARDWARE_ERROR, f"{operation} failed: {error}")
        if len(values) != 10:
            return HardwareResponse.failure(
                BackendCode.INVALID_RESULT,
                f"{operation} returned {len(values)} positions; expected 10",
            )
        try:
            result = JointFeedback(self.side, values, self._clock())
        except Exception as error:
            return HardwareResponse.failure(BackendCode.INVALID_RESULT, f"{operation} returned invalid positions: {error}")
        return HardwareResponse.success_result(result, f"Agilink O10 {operation} completed")

    @classmethod
    def _error_word(cls, report: object) -> int:
        return sum(bit for name, bit in cls._ERROR_BITS if bool(getattr(report, name)))
