from __future__ import annotations

import pytest

from rokoko_omnihand_launchpad.app import create_app
from rokoko_omnihand_launchpad.ros_runtime import RosRuntime


class _FakeRclpy:
    def __init__(self, *, init_error: Exception | None = None) -> None:
        self.init_error = init_error
        self.initialized = False
        self.shutdown_called = False

    def init(self, args=None) -> None:
        if self.init_error is not None:
            raise self.init_error
        self.initialized = True

    def create_node(self, name: str):
        class Node:
            def destroy_node(self) -> None:
                return None

        return Node()

    def spin(self, node) -> None:
        return None

    def ok(self) -> bool:
        return self.initialized

    def shutdown(self) -> None:
        self.shutdown_called = True
        self.initialized = False


class _ImportBlockedAdapter:
    def attach(self, node) -> None:
        raise ImportError("No module named 'rokoko_omnihand_msgs'")


class _AttachedAdapter:
    def __init__(self) -> None:
        self.nodes = []

    def attach(self, node) -> None:
        self.nodes.append(node)


def test_missing_ros_message_dependency_keeps_runtime_fail_soft_and_app_usable():
    rclpy = _FakeRclpy()
    runtime = RosRuntime(rclpy_module=rclpy, data_stream_adapter=_ImportBlockedAdapter())

    runtime.start()

    assert runtime.snapshot() == {
        "status": "unavailable",
        "reason": "missing_dependency",
        "error": "No module named 'rokoko_omnihand_msgs'",
    }
    assert create_app(ros_monitor=runtime.monitor).state.ros_monitor.snapshot()["status"] == "unavailable"
    runtime.stop()


def test_rclpy_init_error_keeps_control_plane_constructible():
    runtime = RosRuntime(rclpy_module=_FakeRclpy(init_error=RuntimeError("context unavailable")))

    runtime.start()

    assert runtime.snapshot() == {
        "status": "error",
        "reason": "rclpy_init",
        "error": "context unavailable",
    }
    app = create_app(ros_monitor=runtime.monitor)
    assert app.state.orchestrator is not None
    assert app.state.ros_monitor.snapshot()["status"] == "error"


def test_available_ros_runtime_attaches_all_configured_adapters():
    rclpy = _FakeRclpy()
    data_stream = _AttachedAdapter()
    latency_events = _AttachedAdapter()
    runtime = RosRuntime(
        rclpy_module=rclpy,
        data_stream_adapter=data_stream,
        latency_adapter=latency_events,
    )

    runtime.start()

    assert runtime.snapshot() == {"status": "available", "reason": "attached"}
    assert len(data_stream.nodes) == 1
    assert len(latency_events.nodes) == 1
    runtime.stop()


def test_orchestrator_exceptions_are_not_hidden_by_ros_monitor_boundary():
    app = create_app()

    with pytest.raises(ValueError, match="unknown block"):
        app.state.orchestrator.configure({"blocks": ["unknown block"]})
