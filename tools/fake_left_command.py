#!/usr/bin/python3
"""Fake left-hand command publisher for testing the O10 control chain.

Publishes a legal ``sensor_msgs/msg/JointState`` to
``/o10_control/left/command``; publishing alone moves the hand (control
requires the feedback / error monitor to be initialised, which happens
automatically once the provider is running).

Legal message contract (from the code, authoritative):
  * ``name`` == ACTIVE_JOINT_NAMES exactly (10 joints, fixed order).
  * ``position`` == 10 values within per-side LEFT limits.
  * ``velocity`` and ``effort`` empty.
  * ``header.frame_id`` == "" and ``header.stamp`` set to a fresh time.

Usage:
  source /opt/ros/jazzy/setup.bash
  source install/setup.bash
  python3 tools/fake_left_command.py --rate 10 --mode close
"""

from __future__ import annotations

import argparse
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

# Mirrors omnihand_o10_contracts.joints.ACTIVE_JOINT_NAMES (Spec decision 24).
ACTIVE_JOINT_NAMES = (
    "thumb_roll",
    "thumb_abad",
    "thumb_mcp",
    "index_abad",
    "index_pip",
    "middle_pip",
    "ring_abad",
    "ring_pip",
    "pinky_abad",
    "pinky_pip",
)

# LEFT per-joint limits (radians) from omnihand_o10_contracts.joints.
_LEFT_LOWER = (
    -1.1213740444063567, -0.04537856055185257, -0.8415977653116657,
    0.0, 0.0, 0.0, -0.16929693744344995, 0.0,
    -0.1850049007113989, 0.0,
)
_LEFT_UPPER = (
    0.029670597283903602, 1.642354826126664, 0.0,
    0.16406094968746698, 1.4835298641951802, 1.4835298641951802,
    0.0, 1.4835298641951802, 0.0, 1.4835298641951802,
)

# A comfortably-in-limit resting posture (mirrors the graph test LEFT_VALID).
REST = (0.0, 0.5, 0.0, 0.1, 0.5, 0.5, 0.0, 0.5, 0.0, 0.5)

# A gentle closed-fist-ish motion (only joints with nonzero ranges move).
CLOSE = (0.0, 0.8, 0.0, 0.1, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0)


def clamp(vec, lo=_LEFT_LOWER, hi=_LEFT_UPPER):
    return tuple(min(max(v, l), h) for v, l, h in zip(vec, lo, hi))


class FakeLeftCommandNode(Node):
    def __init__(self, rate: float) -> None:
        super().__init__("fake_left_command")
        self._pub = self.create_publisher(JointState, "/o10_control/left/command", 10)
        self._rate = rate
        self._t0 = time.monotonic()

    def build(self, position) -> JointState:
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(ACTIVE_JOINT_NAMES)
        msg.position = list(clamp(position))
        # velocity and effort intentionally empty; frame_id intentionally "".
        return msg

    def run(self, mode: str) -> None:
        # Send an initial REST frame so a valid target exists.
        self._pub.publish(self.build(REST))
        period = 1.0 / self._rate
        while rclpy.ok():
            target = REST
            if mode == "wave":
                # Smooth sine sweep on ring_pip (index 7) within limits.
                t = time.monotonic() - self._t0
                target = [0.0, 0.5, 0.0, 0.1, 0.5, 0.5, 0.0, 0.5 + 0.5 * (1 + __import__("math").sin(t * 1.5)) / 1, 0.0, 1.0]
            elif mode == "close":
                # Alternate REST <-> CLOSE every 2 seconds.
                if int((time.monotonic() - self._t0) / 2) % 2 == 0:
                    target = REST
                else:
                    target = CLOSE
            self._pub.publish(self.build(target))
            time.sleep(period)


def main(args=None) -> None:
    rclpy.init(args=args)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=float, default=10.0, help="publish rate Hz")
    parser.add_argument("--mode", choices=["hold", "wave", "close"], default="close")
    namespace, _ = parser.parse_known_args()

    node = FakeLeftCommandNode(namespace.rate)
    try:
        node.run(namespace.mode)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
