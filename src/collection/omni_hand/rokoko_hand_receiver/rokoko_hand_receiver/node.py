"""ROS composition root for the Rokoko JSON v3 receiver."""

from collections import Counter
import math

from geometry_msgs.msg import Point, Quaternion
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.time import Time
from rokoko_omnihand_msgs.msg import RawHandFrame

from .adapters.udp import UdpDatagramReceiver
from .core.decoder import decode_scene, RawHandFrameValue


_FRAME_ID = "rokoko_world_y_up_z_forward"


class RokokoHandReceiverNode(Node):
    """Receive Rokoko UDP scenes and publish validated per-side raw frames."""

    def __init__(self, **kwargs) -> None:
        super().__init__("rokoko_hand_receiver", **kwargs)
        bind_address = self.declare_parameter("bind_address", "0.0.0.0").value
        udp_port = self.declare_parameter("udp_port", 14043).value
        actor_index = self.declare_parameter("actor_index", 0).value
        qos_depth = self.declare_parameter("raw_qos_depth", 10).value
        quaternion_epsilon = self.declare_parameter(
            "quaternion_norm_epsilon", 1e-12
        ).value
        max_datagram_bytes = self.declare_parameter(
            "max_datagram_bytes", 65535
        ).value
        self._validate_parameters(
            bind_address,
            udp_port,
            actor_index,
            qos_depth,
            quaternion_epsilon,
            max_datagram_bytes,
        )
        self._actor_index = actor_index
        self._quaternion_epsilon = quaternion_epsilon
        self._rejections: Counter[str] = Counter()

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=qos_depth,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._raw_publishers = {
            side: self.create_publisher(
                RawHandFrame, f"/rokoko/{side}/raw_hand", qos
            )
            for side in ("left", "right")
        }
        self._udp = UdpDatagramReceiver(
            bind_address,
            udp_port,
            max_datagram_bytes=max_datagram_bytes,
            now_ns=lambda: self.get_clock().now().nanoseconds,
            callback=self._on_datagram,
        )
        self.get_logger().info(
            f"listening for Rokoko JSON v3 on {bind_address}:{udp_port}; "
            f"actor_index={actor_index}"
        )

    @staticmethod
    def _validate_parameters(
        bind_address,
        udp_port,
        actor_index,
        qos_depth,
        quaternion_epsilon,
        max_datagram_bytes,
    ) -> None:
        if not isinstance(bind_address, str) or not bind_address:
            raise ValueError("bind_address must be a non-empty string")
        for name, value, lower, upper in (
            ("udp_port", udp_port, 1, 65535),
            ("actor_index", actor_index, 0, 2**32 - 1),
            ("raw_qos_depth", qos_depth, 1, 2**31 - 1),
            ("max_datagram_bytes", max_datagram_bytes, 1, 65535),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if not lower <= value <= upper:
                raise ValueError(f"{name} must be in [{lower}, {upper}]")
        if (
            isinstance(quaternion_epsilon, bool)
            or not isinstance(quaternion_epsilon, (int, float))
            or not math.isfinite(quaternion_epsilon)
            or quaternion_epsilon < 0.0
        ):
            raise ValueError("quaternion_norm_epsilon must be finite and non-negative")

    def _on_datagram(self, payload: bytes, received_at_ns: int) -> None:
        result = decode_scene(
            payload,
            actor_index=self._actor_index,
            received_at_ns=received_at_ns,
            quaternion_norm_epsilon=self._quaternion_epsilon,
        )
        if result.scene_rejection is not None:
            self._report_rejection("scene", result.scene_rejection)
            return
        for side, reason in result.side_rejections.items():
            self._report_rejection(side, reason)
        for side, frame in result.frames.items():
            self._raw_publishers[side].publish(self._to_message(frame))

    def _report_rejection(self, scope: str, reason: str) -> None:
        key = f"{scope}:{reason}"
        self._rejections[key] += 1
        count = self._rejections[key]
        if count == 1 or count & (count - 1) == 0:
            self.get_logger().warning(
                f"dropped Rokoko {scope} input ({count} occurrence(s)): {reason}"
            )

    @staticmethod
    def _to_message(frame: RawHandFrameValue) -> RawHandFrame:
        message = RawHandFrame()
        message.header.stamp = Time(nanoseconds=frame.received_at_ns).to_msg()
        message.header.frame_id = _FRAME_ID
        message.actor_index = frame.actor_index
        message.actor_name = frame.actor_name
        message.source_timestamp = frame.source_timestamp
        message.node_names = list(frame.node_names)
        message.positions = [Point(x=x, y=y, z=z) for x, y, z in frame.positions]
        message.orientations = [
            Quaternion(x=x, y=y, z=z, w=w) for x, y, z, w in frame.orientations
        ]
        return message

    def destroy_node(self):
        """Close UDP ingress before releasing ROS entities."""
        self._udp.close()
        return super().destroy_node()


def main(args=None) -> None:
    """Run the Rokoko receiver until shutdown."""
    rclpy.init(args=args)
    node = RokokoHandReceiverNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
