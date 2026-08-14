# collection

数据采集阶段。输入是采集设备和场景动作，输出是不可被下游覆盖的 `raw MCAP`。

## Rokoko 接收节点

`omni_hand/rokoko_hand_receiver/` 接收 Rokoko Studio Custom Streaming 的 UDP
JSON v3 场景包，选择一个 Actor，并把完整、合法的左右手 21 节点分别发布到：

```text
/rokoko/left/raw_hand
/rokoko/right/raw_hand
```

节点按官方字段名重排节点，不依赖 JSON 对象成员顺序。场景级错误或 Actor 不存在
时双侧都不发布；单侧缺失、重复、非有限数值或非法四元数只丢弃该侧。Raw 发布
QoS 为 Reliable、Volatile、KeepLast，默认深度 10。

构建并启动：

```bash
source /opt/ros/jazzy/setup.bash
PATH=/usr/bin:/bin:$PATH colcon build \
  --packages-select rokoko_omnihand_msgs rokoko_hand_receiver \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
source install/setup.bash
ros2 run rokoko_hand_receiver rokoko_hand_receiver_node --ros-args \
  -p bind_address:=0.0.0.0 \
  -p udp_port:=14043 \
  -p actor_index:=0
```

离线验收使用 loopback UDP 和公开 Raw Topic，不连接 OmniHand：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
PATH=/usr/bin:/bin:$PATH colcon test \
  --packages-select rokoko_omnihand_msgs rokoko_hand_receiver
PATH=/usr/bin:/bin:$PATH colcon test-result --verbose
```

测试 fixture 根据 Rokoko 官方 Custom Streaming JSON v3 文档构造，并非目标现场
Rokoko Studio 的 UDP 抓包；接入现场前仍需追加一份脱敏真实包做兼容性回归。

## OmniHand O10 双手控制

`omni_hand/jazzy/` 是官方 OmniHand SDK 1.1.8 的 ROS 2 Jazzy 安装空间，保持为第三方运行时，不在其中维护 Dexhit 源码。`omni_hand/omnihand_o10_control/` 提供一个 Python 安全入口，在上游控制目标与官方驱动之间校验左右手的 10 个主动关节角度。

O10 的稳定模块职责、字段语义、关节顺序、限位和失败语义以 [OmniHand O10 控制契约与模块边界](../../DOCS/01_知识/02_OmniHand_O10控制契约与模块边界.md) 为权威；本 README 只说明当前源码的运行和验证入口。

### 构建

在仓库根目录执行：

```bash
source src/collection/omni_hand/setup.bash
colcon build --packages-select omnihand_o10_control
source install/setup.bash
```

### 启动

只启动控制节点，不会自动发布动作：

```bash
ros2 run omnihand_o10_control o10_control_node
```

同时启动官方 O10 驱动和控制节点：

```bash
ros2 launch omnihand_o10_control o10_bringup.launch.py
```

使用独立的官方硬件配置：

```bash
ros2 launch omnihand_o10_control o10_bringup.launch.py \
  config_file:=/absolute/path/to/omnihand_2025_node.yaml
```

默认官方配置将左手绑定到 `can0`、右手绑定到 `can1`。真实设备的接口、设备 ID 和通信参数必须在官方 YAML 中配置。

### ROS 2 接口

| 方向 | 左手 | 右手 | 类型 |
| --- | --- | --- | --- |
| 上游目标输入 | `/o10_control/left/command` | `/o10_control/right/command` | `sensor_msgs/msg/JointState` |
| 官方驱动命令 | `/o10/left/joint_cmd` | `/o10/right/joint_cmd` | `sensor_msgs/msg/JointState` |
| 官方位置反馈 | `/o10/left/joint_states` | `/o10/right/joint_states` | `sensor_msgs/msg/JointState` |

输入只消费 `position`。其完整约束和左右手关节范围见上述权威知识页。

> 向输入话题发布合法消息会造成实体手运动。真机测试前必须清空手周围物体、确认急停可用并使用已经验证的安全目标。

### 当前边界

- 收到一帧立即转发一帧；没有定时器、插值、重复发布或 stale-command watchdog。
- 不实现 Rokoko 解析、人体到机器人重定向、速度限制、混合力控、触觉和反馈代理。
- `joint_states` 是官方驱动在收到 `joint_cmd` 后触发式发布，不是由本控制节点周期查询。
- 当前只完成离线 ROS 2 验证，没有执行 CAN 或实体手动作验收。

### 离线验证

```bash
colcon test --packages-select omnihand_o10_control
colcon test-result --verbose
```
