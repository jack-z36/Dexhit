cmake_minimum_required(VERSION 3.10)
project(rokoko_omnihand_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

# This package owns the wire schema and the numeric enum values for the
# Rokoko-to-OmniHand O10 teleoperation system (architecture invariant A16).
# It owns no nodes, algorithms, state or config defaults.
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/RawHandFrame.msg"
  "msg/RetargetingState.msg"
  "msg/O10ControlState.msg"
  "srv/ReadO10ActiveJoints.srv"
  "srv/ControlOperation.srv"
  DEPENDENCIES std_msgs geometry_msgs builtin_interfaces
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  # ROS Jazzy's launch_testing pytest plugins are incompatible with the
  # system pytest 9.x hookspec (PluginValidationError on collection). These
  # tests are plain pytest and need no auto-loaded plugins, so disable
  # autoload (mirrors omnihand_o10_model).
  ament_add_pytest_test(smoke_test test/test_smoke.py
    TIMEOUT 60
    ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  )
endif()

ament_package()
