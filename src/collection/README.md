# Collection

Collection 阶段接入采集设备和场景动作，并保护不可被下游覆盖的 `raw MCAP`。本目录按“生产期长驻节点优先”组织：顶层五个 `_node` 目录一眼可见运行角色，接口、模型、bringup 和测试统一放在 `teleoperation_support/`，第三方 SDK 隔离在 `third_party/`。

```text
src/collection/
├── rokoko_hand_receiver_node/                 # Rokoko UDP 接收节点
├── hand_retargeting_node/                     # 人手到 O10 重定向节点
├── omnihand_o10_control_node/                 # O10 安全控制节点
├── omnihand_o10_hardware_provider_node/       # O10 真机 Provider
├── rokoko_omnihand_launchpad_node/            # 本机网页控制面
├── teleoperation_support/                     # 接口、模型、bringup、测试
└── third_party/                               # colcon 忽略的 vendor 前缀
```

物理目录名不改变 ROS 公共接口。ROS package 仍为 `rokoko_hand_receiver`、`hand_retargeting`、`omnihand_o10_control`、`omnihand_o10_hardware_adapter` 和 `rokoko_omnihand_launchpad`；Topic、Service、参数和 executable 名保持不变。五个顶层目录中，前三个是稳定业务节点，硬件 Provider 是设备 Adapter，Launchpad 是 Composition/External 控制面。

## 标准软件自检

在仓库根目录执行：

```bash
./init_omnihand.sh
```

脚本显式构建 11 个 Dexhit package，并分别运行原十包基线和 Launchpad 测试。它默认拒绝遗留的 Rokoko/O10 ROS 图，不启动节点、不发布命令、不清故障，也不驱动实体手。依赖安装必须显式使用 `--install`；其他选项见 `./init_omnihand.sh --help`。

手工构建时使用 Collection 源码根即可；`third_party/COLCON_IGNORE` 会排除 vendor：

```bash
source /opt/ros/jazzy/setup.bash
colcon build --base-paths src/collection --symlink-install
source install/setup.bash
```

## 标准启动入口

真实 Rokoko → 重定向 → HCAN Provider → O10 控制链只通过仓库根入口启动：

```bash
./start_omnihand_control.sh
```

根脚本把参数原样转给 `teleoperation_support/production_bringup/` 的实现，自动锚定 worktree，并保持既有启动顺序、节点名、日志和停止语义。当前控制契约没有 arm/disarm 门：反馈就绪后，新鲜合法目标可能直接驱动实体手；启动前必须按全流程手册完成环境、反馈、错误和急停检查。

Launchpad 控制面入口保持：

```bash
./start_launchpad.sh
```

它默认只启动 `127.0.0.1:8710` 的控制面，不等同于启动业务节点。`./clear_o10_fault.sh` 与 `./decode_rokoko_udp.sh` 的命令接口也保持不变。

## Rokoko 接收接口

`rokoko_hand_receiver_node/` 接收 Rokoko Studio Custom Streaming 的 UDP JSON v3 场景包，选择 Actor，并把完整合法的左右手 21 节点分别发布到：

```text
/rokoko/left/raw_hand
/rokoko/right/raw_hand
```

节点按官方字段名重排，不依赖 JSON 对象成员顺序。场景级错误或 Actor 不存在时双侧都不发布；单侧缺失、重复、非有限数值或非法四元数只丢弃该侧。Raw QoS 为 Reliable、Volatile、KeepLast，默认深度 10。

## OmniHand O10 接口与 vendor

Agilink OmniHand SDK 1.1.8 的 x64/Jazzy 安装前缀位于 `third_party/agillink_omnihand_sdk/linux/x64/ros2/jazzy/`。它是固定来源的第三方运行时，不承载 Dexhit 源码；来源和升级约束见 [third_party/README.md](third_party/README.md)。

主要 ROS wire 接口保持：

| 方向 | 左手 | 右手 | 类型 |
| --- | --- | --- | --- |
| Raw 输入 | `/rokoko/left/raw_hand` | `/rokoko/right/raw_hand` | `rokoko_omnihand_msgs/msg/RawHandFrame` |
| 重定向状态 | `/hand_retargeting/left/state` | `/hand_retargeting/right/state` | `rokoko_omnihand_msgs/msg/RetargetingState` |
| 软目标 | `/o10_control/left/command` | `/o10_control/right/command` | `sensor_msgs/msg/JointState` |
| 厂商最终命令 | `/o10/left/joint_cmd` | `/o10/right/joint_cmd` | `sensor_msgs/msg/JointState` |
| 厂商反馈 | `/o10/left/joint_states` | `/o10/right/joint_states` | `sensor_msgs/msg/JointState` |

O10 的字段语义、关节顺序、限位和失败语义以 [OmniHand O10 控制契约与模块边界](../../DOCS/01_知识/02_OmniHand_O10控制契约与模块边界.md) 为权威。

> 向控制 Topic 发布合法消息可能造成实体手运动。软件构建和测试通过不代表真实硬件可动作。
