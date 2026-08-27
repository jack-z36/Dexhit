"""Production composition with explicit configuration and vendor launch inputs.

The launch file deliberately has no operational defaults.  A production
operator must provide both the complete parameter file and the formally
approved vendor-node launch description.  The deterministic test Provider is
outside this composition and is never referenced here.
"""

from __future__ import annotations

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _require_file(context, name: str) -> Path:
    value = context.launch_configurations.get(name)
    if not value:
        raise RuntimeError(f"required production launch argument is missing: {name}")
    path = Path(value)
    if not path.is_file():
        raise RuntimeError(f"required production launch file does not exist: {path}")
    return path


def _compose(context):
    parameter_file = _require_file(context, "parameters")
    vendor_launch = _require_file(context, "vendor_launch")
    return [
        Node(
            package="rokoko_hand_receiver",
            executable="rokoko_hand_receiver_node",
            name="rokoko_hand_receiver",
            parameters=[str(parameter_file)],
            output="screen",
        ),
        Node(
            package="hand_retargeting",
            executable="hand_retargeting_node",
            name="hand_retargeting",
            parameters=[str(parameter_file)],
            output="screen",
        ),
        Node(
            package="omnihand_o10_control",
            executable="omnihand_o10_control_node",
            name="omnihand_o10_control",
            parameters=[str(parameter_file)],
            output="screen",
        ),
        Node(
            package="omnihand_o10_hardware_adapter",
            executable="omnihand_o10_hardware_provider",
            name="omnihand_o10_hardware_adapter",
            parameters=[str(parameter_file)],
            output="screen",
        ),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(vendor_launch))),
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "parameters",
                description="Complete production parameter YAML; no defaults are allowed.",
            ),
            DeclareLaunchArgument(
                "vendor_launch",
                description="Approved external vendor-node launch; no defaults are allowed.",
            ),
            OpaqueFunction(function=_compose),
        ]
    )
