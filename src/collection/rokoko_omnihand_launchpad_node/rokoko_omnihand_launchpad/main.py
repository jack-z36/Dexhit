"""Executable entrypoint for the local Launchpad control plane."""

from __future__ import annotations

import sys

import uvicorn

from .app import create_app
from .data_stream import DataStreamStore
from .latency_events import LatencyEventsStore
from .instance_lock import InstanceAlreadyRunning, InstanceLock
from .ros_runtime import RosRuntime


HOST = "127.0.0.1"
PORT = 8710


def main() -> int:
    """Run the local-only HTTP control plane and release its lock on exit."""

    lock = InstanceLock()
    try:
        lock.acquire()
    except InstanceAlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        data_stream = DataStreamStore()
        latency_events = LatencyEventsStore()
        app = create_app(data_stream=data_stream, latency_events=latency_events)
        ros_runtime = RosRuntime(data_stream, latency_events, monitor=app.state.ros_monitor)
        ros_runtime.start()
        uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    finally:
        ros_runtime.stop()
        lock.release()
    return 0
