"""Optional ROS runtime thread for the Launchpad control-plane process."""

from __future__ import annotations

import threading
from types import ModuleType
from typing import Any

from .data_stream import DataStreamStore, RosDataStreamAdapter
from .latency_events import RosLatencyEventsAdapter


class RosMonitorState:
    """Observable state for the optional ROS monitoring layer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, str] = {
            "status": "unavailable",
            "reason": "not_started",
        }

    def update(self, status: str, reason: str, error: str | None = None) -> None:
        state = {"status": status, "reason": reason}
        if error:
            state["error"] = error
        with self._lock:
            self._state = state

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._state)


class RosRuntime:
    """Spin one control-plane ROS node without starting business nodes."""

    def __init__(
        self,
        data_stream: DataStreamStore | None = None,
        latency_events=None,
        *,
        monitor: RosMonitorState | None = None,
        rclpy_module: ModuleType | Any | None = None,
        data_stream_adapter: Any | None = None,
        latency_adapter: Any | None = None,
    ) -> None:
        self.monitor = monitor or RosMonitorState()
        self._rclpy_override = rclpy_module
        self._rclpy: ModuleType | None = None
        self._node = None
        self._thread: threading.Thread | None = None
        self._data_stream_adapter = data_stream_adapter or (
            RosDataStreamAdapter(data_stream) if data_stream else None
        )
        self._latency_adapter = latency_adapter or (
            RosLatencyEventsAdapter(latency_events) if latency_events else None
        )

    def start(self) -> None:
        if self._rclpy_override is not None:
            rclpy = self._rclpy_override
        else:
            try:
                import rclpy
            except ImportError as exc:
                # The HTTP control plane remains runnable outside a sourced
                # ROS shell; the optional monitor is explicitly unavailable.
                self.monitor.update("unavailable", "missing_dependency", str(exc))
                return

        self._rclpy = rclpy
        try:
            rclpy.init(args=None)
            self._node = rclpy.create_node("rokoko_omnihand_launchpad")
            if self._data_stream_adapter is not None:
                self._data_stream_adapter.attach(self._node)
            if self._latency_adapter is not None:
                self._latency_adapter.attach(self._node)
        except ImportError as exc:
            self._cleanup_failed_start()
            self.monitor.update("unavailable", "missing_dependency", str(exc))
            return
        except Exception as exc:
            self._cleanup_failed_start()
            self.monitor.update("error", "rclpy_init" if self._node is None else "attach", str(exc))
            return

        self.monitor.update("available", "attached")
        self._thread = threading.Thread(
            target=rclpy.spin,
            args=(self._node,),
            name="launchpad-rclpy-spin",
            daemon=True,
        )
        self._thread.start()

    def snapshot(self) -> dict[str, str]:
        return self.monitor.snapshot()

    def _cleanup_failed_start(self) -> None:
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None
        if self._rclpy is not None:
            try:
                if self._rclpy.ok():
                    self._rclpy.shutdown()
            except Exception:
                pass
        self._rclpy = None

    def stop(self) -> None:
        if self._rclpy is None:
            return
        if self._node is not None:
            self._node.destroy_node()
            self._node = None
        if self._rclpy.ok():
            self._rclpy.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._rclpy = None
