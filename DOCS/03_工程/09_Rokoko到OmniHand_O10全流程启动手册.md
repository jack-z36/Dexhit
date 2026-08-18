# Rokoko 到 OmniHand O10 全流程启动手册

本文面向第一次运行系统的操作者，说明如何启动并检查完整链路：

```text
Rokoko Studio
    ↓ UDP 14043
rokoko_hand_receiver
    ↓ /rokoko/{side}/raw_hand
hand_retargeting
    ↓ /o10_control/{side}/command
omnihand_o10_hardware_provider
    ↓ /o10/{side}/joint_cmd
OmniHand O10
```

## 重要安全说明

启动节点不等于允许实体手运动。本文的启动命令不会调用 `arm` Service；控制节点启动后应保持：

```text
armed: false
motion_enabled: false
```

只有完成反馈、错误和目标状态检查，并确认实体手周围安全后，才可以单独调用左手 `arm`。

当前 Provider 会同时初始化左右两侧。即使本次只 arm 左手，Provider 仍会尝试读取右手。如果只有左手实体手接入，当前实现可能因右手初始化/反馈失败而不能完成双侧 Provider 启动；不能用错误的右手参数绕过这个限制。

## 方式 A：推荐的一键启动

### 终端 0：停止旧进程

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 node list
```

如果看到以下任意节点，请回到启动它们的终端按 `Ctrl+C`：

```text
/rokoko_hand_receiver
/hand_retargeting
/omnihand_o10_hardware_provider
/o10_control_node
```

### 终端 1：一键启动整条链路

```bash
cd "$(git rev-parse --show-toplevel)"
bash src/collection/omni_hand/rokoko_omnihand_bringup/scripts/start_omnihand_control.sh
```

脚本会依次启动接收节点、重定向节点、HCAN Provider 和 O10 控制节点；日志写入 `/tmp/omnihand-control-<timestamp>/`。保持终端 1 运行，按 `Ctrl+C` 会停止本次脚本启动的子节点。脚本不会调用任何 `arm` Service。

## 方式 B：手动分终端启动

手动方式使用 6 个终端。每个持续运行的节点终端都不要关闭。

### 终端 0：公共环境准备

每个新终端先执行：

```bash
export COLLECTION_ROOT="$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source "$COLLECTION_ROOT/install/setup.bash"
```

### 终端 1：Rokoko 接收节点

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run rokoko_hand_receiver rokoko_hand_receiver_node --ros-args \
  -p bind_address:=0.0.0.0 \
  -p udp_port:=14043 \
  -p actor_index:=0
```

### 终端 2：手部重定向节点

不要使用 `ros2 run hand_retargeting hand_retargeting_node`；使用项目 wrapper：

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export DEXHIT_COLLECTION_PREFIX=/home/hit/miniforge3/envs/dexhit_collection
export OMNIHAND_O10_MODEL_FIXTURE=/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009

bash src/collection/omni_hand/hand_retargeting/scripts/hand_retargeting_node \
  --ros-args \
  --params-file runs/retargeting_diag_params.yaml \
  -p recovery_confirmation_timeout_sec:=0.5
```

### 终端 3：HCAN O10 Provider

先确认设备：

```bash
lsusb -d a8fa:8598
```

然后启动：

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export DEXHIT_COLLECTION_PREFIX=/home/hit/miniforge3/envs/dexhit_collection
export PYTHONNOUSERSITE=1
export PYTHONPATH=/home/hit/miniforge3/envs/dexhit_collection/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}
export LD_LIBRARY_PATH=/home/hit/miniforge3/envs/dexhit_collection/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

ros2 run omnihand_o10_hardware_adapter omnihand_o10_hardware_provider \
  --ros-args \
  -p o10.left.transport:=hcan \
  -p o10.left.hand_device_id:=1 \
  -p o10.left.canfd_device_id:=0 \
  -p o10.left.canfd_channel_id:=0 \
  -p o10.right.transport:=hcan \
  -p o10.right.hand_device_id:=1 \
  -p o10.right.canfd_device_id:=0 \
  -p o10.right.canfd_channel_id:=1
```

成功日志应包含：

```text
Device 0, channel 0 opened successfully
Device 0 channel 1 opened successfully
Receive thread started
```

### 终端 4：O10 控制节点

复制粘贴下面整段命令。它只启动控制节点，不会自动 arm：

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run omnihand_o10_control o10_control_node \
  --ros-args \
  -p 'left.max_joint_rates:=[0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]' \
  -p left.max_time_credit:=0.1 \
  -p 'left.slew_compare_epsilon:=[0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001]' \
  -p left.target_input_stale_timeout:=2.0 \
  -p left.target_receive_stale_timeout:=2.0 \
  -p left.control_check_period:=0.05 \
  -p left.error_poll_period:=0.2 \
  -p left.error_query_timeout:=0.5 \
  -p left.command_readback_timeout:=2.0 \
  -p left.provider_heartbeat_timeout:=3.0 \
  -p left.init_read_retry_period:=0.1 \
  -p left.init_error_retry_period:=0.1 \
  -p left.read_service_timeout:=1.0 \
  -p left.clear_fault_error_timeout:=1.0 \
  -p left.clear_fault_read_timeout:=1.0 \
  -p 'right.max_joint_rates:=[0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]' \
  -p right.max_time_credit:=0.1 \
  -p 'right.slew_compare_epsilon:=[0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001]' \
  -p right.target_input_stale_timeout:=2.0 \
  -p right.target_receive_stale_timeout:=2.0 \
  -p right.control_check_period:=0.05 \
  -p right.error_poll_period:=0.2 \
  -p right.error_query_timeout:=0.5 \
  -p right.command_readback_timeout:=2.0 \
  -p right.provider_heartbeat_timeout:=3.0 \
  -p right.init_read_retry_period:=0.1 \
  -p right.init_error_retry_period:=0.1 \
  -p right.read_service_timeout:=1.0 \
  -p right.clear_fault_error_timeout:=1.0 \
  -p right.clear_fault_read_timeout:=1.0
```

### 终端 5：检查整条 ROS 链

```bash
ros2 node list
ros2 topic hz /rokoko/left/raw_hand
ros2 topic hz /o10_control/left/command
ros2 topic info -v /o10_control/left/command
ros2 topic echo /o10_control/left/state
```

应至少看到四个节点：

```text
/rokoko_hand_receiver
/hand_retargeting
/omnihand_o10_hardware_provider
/o10_control_node
```

正常状态重点是：

```text
feedback_ready: true
error_monitor_ready: true
target_ready: true
target_fresh: true
armed: false
motion_enabled: false
fault_latched: false
```

检查左手只读反馈：

```bash
ros2 service call /o10/left/read_active_joints rokoko_omnihand_msgs/srv/ReadO10ActiveJoints '{}'
```

成功时应看到 `success=True`、`result_code=0`，并返回 10 个位置。

### 终端 6：只 arm 左手

只有终端 5 确认 `feedback_ready: true`、`target_ready: true`、`fault_latched: false`，且实体手周围安全时，才执行：

```bash
source /opt/ros/jazzy/setup.bash
source "$(git rev-parse --show-toplevel)/install/setup.bash"

ros2 service call /o10_control/left/arm rokoko_omnihand_msgs/srv/ControlOperation '{}'
```

成功时应看到 `success=True` 和 `message='armed'`。本次只调用左手，不调用右手 `arm`。

## 停止流程

一键启动时回到终端 1 按 `Ctrl+C`。手动启动时依次在对应终端按 `Ctrl+C`：

```text
终端 4：o10_control_node
终端 3：omnihand_o10_hardware_provider
终端 2：hand_retargeting
终端 1：rokoko_hand_receiver
```

如果实体手已经 arm，先执行：

```bash
ros2 service call /o10_control/left/disarm rokoko_omnihand_msgs/srv/ControlOperation '{}'
```

## 常见现象

| 现象 | 处理 |
| --- | --- |
| `/rokoko/left/raw_hand` 没有频率 | 检查 Rokoko Studio IP、UDP 端口 14043 和 Actor |
| `/o10_control/left/command` 没有频率 | 查看 `/hand_retargeting/left/state` 的 `phase`、`ready` 和 `ik_state` |
| `No module named pinocchio` | 使用终端 2 的源码 wrapper，不用 `ros2 run hand_retargeting ...` |
| `Failed to open device` | 检查 HCAN 权限、USB-CANFD、供电和设备占用 |
| `fault_latched: true` | 不要 arm，查看 `hardware_error_bits` |
| `commu_except` 或数值 `16` | 检查 O10 电源、CAN 线、通道和设备状态 |
| `/o10/right/joint_error_cmd` 出现 `{}` | 正常的 Empty 错误查询请求 |
| `read_active_joints returned 0 positions` | 对应侧没有读到 10 个关节反馈 |

