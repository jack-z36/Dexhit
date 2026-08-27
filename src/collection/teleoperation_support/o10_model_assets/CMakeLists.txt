cmake_minimum_required(VERSION 3.10)
project(omnihand_o10_model)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

# Install the pure-Python asset loader / structural validators. The package is
# node-less: there are no executables, no rclpy nodes and no ROSIDL interfaces.
# This module may be imported by the hand_retargeting model adapter to obtain a
# validated, parsed representation of the version-locked assets.
ament_python_install_package(${PROJECT_NAME}
  PACKAGE_DIR ${PROJECT_NAME})

# Ament package marker so the package is discoverable via the package index.
install(
  FILES resource/${PROJECT_NAME}
  DESTINATION share/ament_index/resource_index/packages
)

install(
  FILES package.xml
  DESTINATION share/${PROJECT_NAME}
)

# Install the provenance / asset manifest templates and the structural contract
# reference. These describe the expected asset layout; they are NOT the upstream
# model files, which are not vendored pending license confirmation (ADR-0007).
install(
  DIRECTORY templates
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  file(GLOB TEST_FILES test/test_*.py)
  # ROS Jazzy's launch_testing / launch_testing_ros pytest entry-points are
  # incompatible with the system pytest 9.x (PluginValidationError on
  # pytest_pycollect_makemodule). Our tests are plain pytest and need no
  # auto-loaded plugins, so disable plugin auto-load for the test run.
  set(_OMNI_TEST_ENV "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1")
  foreach(TEST_FILE ${TEST_FILES})
    get_filename_component(TEST_NAME ${TEST_FILE} NAME_WE)
    ament_add_pytest_test(${TEST_NAME} ${TEST_FILE} ENV ${_OMNI_TEST_ENV})
  endforeach()
endif()

ament_package()
