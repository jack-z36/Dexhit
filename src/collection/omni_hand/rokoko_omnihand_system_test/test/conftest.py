"""Process-scoped ROS context for the public system-test harness."""

import pytest
import rclpy


@pytest.fixture(scope="session", autouse=True)
def ros_context():
    """Initialize ROS once; each test still creates its own disposable graph."""
    owned_context = not rclpy.ok()
    if owned_context:
        rclpy.init()
    try:
        yield
    finally:
        if owned_context and rclpy.ok():
            rclpy.shutdown()
