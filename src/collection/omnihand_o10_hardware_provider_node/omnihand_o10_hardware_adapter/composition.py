"""Pure production composition for the external O10 SDK Provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from omnihand_o10_contracts import Side

from .application.provider import O10HardwareProviderApplication
from .backends import AgilinkO10Backend

__all__ = ["build_production_applications", "production_parameter_defaults"]


_TRANSPORT_KEYS = (
    "canfd_device_id",
    "canfd_channel_id",
    "can_interface",
    "uart_port",
    "host",
    "port",
)


def production_parameter_defaults(side: Side) -> dict[str, object]:
    """Return non-operational sentinels for one side's required parameters."""

    prefix = f"o10.{side.value}."
    return {
        f"{prefix}transport": "",
        f"{prefix}hand_device_id": 0,
        f"{prefix}canfd_device_id": -1,
        f"{prefix}canfd_channel_id": -1,
        f"{prefix}can_interface": "",
        f"{prefix}uart_port": "",
        f"{prefix}host": "",
        f"{prefix}port": -1,
        # E5 diagnostic experiment: global SDK request interval in ms.
        # -1 keeps the vendor default untouched; 0..100 is the documented
        # set_request_interval range where 0 disables throttling entirely.
        f"{prefix}request_interval_ms": -1,
    }


def build_production_applications(
    parameters: Mapping[str, object],
    *,
    sides: tuple[Side, ...] = (Side.LEFT, Side.RIGHT),
    backend_factory: Callable[..., AgilinkO10Backend] = AgilinkO10Backend.from_sdk,
) -> dict[Side, O10HardwareProviderApplication]:
    """Build the production Applications for the requested sides or fail.

    An unselected side gets no Application and never reaches the SDK.
    """

    applications: dict[Side, O10HardwareProviderApplication] = {}
    for side in sides:
        prefix = f"o10.{side.value}."
        transport = _required(parameters, f"{prefix}transport")
        hand_device_id = _required(parameters, f"{prefix}hand_device_id")
        if not isinstance(hand_device_id, int) or isinstance(hand_device_id, bool):
            raise RuntimeError(f"required production parameter is not an integer: {prefix}hand_device_id")

        kwargs: dict[str, object] = {
            "transport": transport,
            "hand_device_id": hand_device_id,
        }
        for key in _TRANSPORT_KEYS:
            value = parameters.get(f"{prefix}{key}")
            if value not in (None, "", -1):
                kwargs[key] = value

        request_interval = parameters.get(f"{prefix}request_interval_ms")
        if request_interval not in (None, "", -1):
            if not isinstance(request_interval, int) or isinstance(request_interval, bool):
                raise RuntimeError(
                    f"required production parameter is not an integer: "
                    f"{prefix}request_interval_ms"
                )
            if not 0 <= request_interval <= 100:
                raise RuntimeError(
                    f"{prefix}request_interval_ms is outside the documented "
                    f"SDK range 0..100: {request_interval}"
                )
            kwargs["request_interval_ms"] = request_interval

        try:
            backend = backend_factory(side, **kwargs)
        except Exception as error:
            raise RuntimeError(
                f"failed to construct production O10 Provider for {side.value}: {error}"
            ) from error
        applications[side] = O10HardwareProviderApplication(side, backend)
    return applications


def _required(parameters: Mapping[str, object], name: str) -> object:
    value = parameters.get(name)
    if value in (None, "", -1):
        raise RuntimeError(f"required production parameter is missing: {name}")
    return value
