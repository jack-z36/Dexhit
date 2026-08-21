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

> **当前实现（`4fedfaa` 起）已移除 `arm`/`disarm`，运动由新鲜合法软目标直接驱动。** 只要反馈就绪、错误监控就绪、目标就绪且目标新鲜，`motion_enabled` 即为 true，重定向节点向 `/o10_control/{side}/command` 发布的每条新目标都会驱动实体手产生命令；停止发布新目标（或目标 2 秒内不更新）即自动暂停。因此：

- 启动完整真机链后，**只要戴着手套并移动手，实体手就会跟着动**。开始前必须确认实体手周围无遮挡、人员与设备安全。
- 不要同时点亮合成输入源与真机 provider：合成假帧喂进真机链会直接驱动实体手。
- 手动中断运动：停止向 `/o10_control/{side}/command` 发布（如收起手套、移出 Rokoko 有效区或停掉重定向节点）；若发生 `fault_latched`，先检查 `hardware_error_bits`，确认致命错误位（bit0–bit3）清零后调用 `clear_fault`。
- 操作者唯一的操作 Service 是每侧 `/o10_control/{side}/clear_fault`；不存在 `arm`/`disarm` Service。

状态观察重点（控制节点启动并读取反馈后）：

```text
feedback_ready: true
error_monitor_ready: true
target_ready: true
target_fresh: true   # 目标新鲜才允许运动
fault_latched: false
motion_enabled: true  # 上三项就绪且目标新鲜时为 true
```

当前 Provider 会同时初始化左右两侧。如果只有左手实体手接入，右手可能因无反馈而不能完成初始化；只要 Provider 进程仍在运行、左手状态满足安全条件，可继续单独观察左手，不要用错误的右手参数绕过限制。

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
bash ./start_omnihand_control.sh
```

脚本会依次启动接收节点、重定向节点、HCAN Provider 和 O10 控制节点；日志写入 `/tmp/omnihand-control-<timestamp>/`。保持终端 1 运行，按 `Ctrl+C` 会停止本次脚本启动的子节点。脚本不调用任何操作 Service（`arm`/`disarm` 已移除，也不调用 `clear_fault`）。

## 仅测试左手：推荐操作顺序

如果你的目标是“只让左手参与本次测试”（且只有左手实体手接入），请按下面的规则执行：

1. 仍然启动完整节点图，因为当前 Provider 会同时创建左右两个侧别，且没有真正的 Provider `left_only` 模式；
2. 只观察左手 Topic 和左手状态，不要刻意初始化右手；
3. 由于运动由目标直接驱动，只要左手反馈就绪且目标新鲜，左手运动即自动开启；安全确认后戴上手套即可测试左手动作，无需任何 arm；
4. 右手出现 `read_active_joints returned 0 positions` 时，说明右手没有反馈，不要用错误的参数伪造右手；只要 Provider 进程仍在运行且左手状态满足安全条件，可以继续单独观察左手。

启动一键脚本后，在终端 2 或新的终端中只检查左手：

```bash
source /opt/ros/jazzy/setup.bash
source "$(git rev-parse --show-toplevel)/install/setup.bash"

ros2 topic hz /rokoko/left/raw_hand
```

看到约 `30 Hz` 后，按 `Ctrl+C` 停止这个频率观察，再执行：

```bash
ros2 topic hz /o10_control/left/command
```

看到约 `30 Hz` 后，再开一个终端执行左手只读反馈：

```bash
source /opt/ros/jazzy/setup.bash
source "$(git rev-parse --show-toplevel)/install/setup.bash"

ros2 service call /o10/left/read_active_joints rokoko_omnihand_msgs/srv/ReadO10ActiveJoints '{}'
```

必须看到：

```text
success=True
result_code=0
```

然后观察左手控制状态：

```bash
ros2 topic echo /o10_control/left/state
```

确认实体手周围安全、状态满足以下条件后，才戴上手套开始左手动作测试（满足即自动运动，无需 arm）：

```text
feedback_ready: true
error_monitor_ready: true
target_ready: true
target_fresh: true
fault_latched: false
motion_enabled: true
```

动作测试期间继续观察左手状态：

```bash
ros2 topic echo /o10_control/left/state
```

如果看到 `fault_latched: true`、`hardware_error_bits` 非零（致命位 bit0–bit3）或实体手动作异常，先停止移动手套/收起手，检查硬件错误位，确认产生原因并解决后再调用左手 `clear_fault`：

```bash
ros2 service call /o10_control/left/clear_fault rokoko_omnihand_msgs/srv/ControlOperation '{}'
```

确认实体手周围安全后，再戴上手套恢复测试。停止时按 `Ctrl+C` 关闭启动终端即可（本轮不再需要任何 disarm）。

注意：当前实现还没有真正的 Provider `left_only` 模式。上面的流程是“完整启动图、只关注左手”，不是“只创建左手 Provider”。

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
  -p o10.right.canfd_device_id:=1 \
  -p o10.right.canfd_channel_id:=0
```

成功日志应包含：

```text
Device 0, channel 0 opened successfully
Device 1, channel 0 opened successfully
Receive thread started
```

### 终端 4：O10 控制节点

复制粘贴下面整段命令。它只启动控制节点；运动由后续新鲜目标自动驱动，无需也不存在 `arm` 调用：

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
fault_latched: false
motion_enabled: true    # 上三项就绪且目标新鲜即 true
```

检查左手只读反馈：

```bash
ros2 service call /o10/left/read_active_joints rokoko_omnihand_msgs/srv/ReadO10ActiveJoints '{}'
```

成功时应看到 `success=True`、`result_code=0`，并返回 10 个位置。

### 终端 6：故障清除

自 `4fedfaa` 起不存在 `arm`/`disarm`；运动由新鲜目标直接驱动，无需授权。若终端 5 看到 `fault_latched: true` 且致命错误位（bit0–bit3）已清零、通信健康、确认实体手周围安全，可对侧别清除锁存故障：

```bash
source /opt/ros/jazzy/setup.bash
source "$(git rev-parse --show-toplevel)/install/setup.bash"

ros2 service call /o10_control/left/clear_fault rokoko_omnihand_msgs/srv/ControlOperation '{}'
```

成功时应看到 `success=True`。清除故障后运动不会立即恢复；下一条新鲜合法软目标到达时才自动恢复。若致命错误位仍非零，先解决硬件原因，不要盲目清除。

## 停止流程

手动中断实体手运动：停止发布新鲜目标即可（收起手套、移出 Rokoko 有效区，或在下游停掉重定向/控制节点）；节点停止即自动停止产生命令。

一键启动时回到终端 1 按 `Ctrl+C`。手动启动时依次在对应终端按 `Ctrl+C`：

```text
终端 4：o10_control_node
终端 3：omnihand_o10_hardware_provider
终端 2：hand_retargeting
终端 1：rokoko_hand_receiver
```

不需要也无 `disarm` 调用。

## 常见现象

| 现象 | 处理 |
| --- | --- |
| `/rokoko/left/raw_hand` 没有频率 | 检查 Rokoko Studio IP、UDP 端口 14043 和 Actor |
| 接收节点日志持续 `configured actor does not exist (Rokoko scene has no actor)` | Rokoko 场景里**根本没有角色**：数据虽然到了 UDP 14043，但包内 `actors` 为空。软件无数据可解。请到 Rokoko Studio 确认手套已配对/校准且场景里能看到手模型，再启动。 |
| 接收节点日志 `actor_index=… out of range; auto-using actor index 0` | 已自动容错：配置的 `actor_index` 越界但场景里有角色，接收节点自动改用 0 号角色继续收发，**不会**丢帧。若 Data 属于另一角色，把 `actor_index` 改成该角色序号即可。 |
| `/o10_control/left/command` 没有频率 | 查看 `/hand_retargeting/left/state` 的 `phase`、`ready` 和 `ik_state` |
| `No module named pinocchio` | 使用终端 2 的源码 wrapper，不用 `ros2 run hand_retargeting ...` |
| `Failed to open device` | 检查 HCAN 权限、USB-CANFD、供电和设备占用 |
| `fault_latched: true` | 查看 `hardware_error_bits`；确认致命位清零与通信健康后调用 `clear_fault` |
| `commu_except` 或数值 `16` | 厂商历史通信标记（bit4），不锁存故障、不阻止控制；仍检查 O10 电源、CAN 线、通道和设备状态 |
| `/o10/right/joint_error_cmd` 出现 `{}` | 正常的 Empty 错误查询请求 |
| `read_active_joints returned 0 positions` | 对应侧没有读到 10 个关节反馈 |
