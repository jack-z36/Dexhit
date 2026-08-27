# ADR-0013：Collection 源码按生产节点优先组织

- 状态：Accepted
- 日期：2026-08-24
- 范围：`src/collection/` 的物理源码布局

## 背景

原 `src/collection/omni_hand/` 同时容纳生产节点、接口、模型、bringup、测试和厂商安装前缀。只看顶层目录无法识别运行角色，第三方二进制与 Dexhit 源码也缺少清晰边界。把全部 ROS package 继续平铺会暴露过多非节点目录；重新增加一个 `omni_hand/` 聚合层则会恢复同样的导航问题。

## 决策

1. `src/collection/` 顶层只保留五个生产期长驻节点目录、`teleoperation_support/` 和 `third_party/`。节点物理目录使用职责名与 `_node` 后缀。
2. `teleoperation_support/` 集中消息、契约、模型、生产 bringup、系统测试和架构测试。它只是组织容器，不创建同名 package、不提供公共 import，也不是 `common/utils` 依赖汇。
3. `third_party/` 由根 `COLCON_IGNORE` 隔离。Agilink SDK 固定在 `agillink_omnihand_sdk/linux/x64/ros2/jazzy/`，Dexhit 源码不得混入 vendor 前缀。
4. 物理目录重排不修改 ROS package 名、executable、节点名、Topic、Service、参数或消息 schema。package 依赖 DAG 继续只用 ROS package 名表达。
5. 顶层五个目录是“生产期进程目录”，不是“五个业务模块”：Rokoko 接收、手部重定向、O10 控制是三个稳定业务节点；硬件 Provider 是设备 Adapter；Launchpad 是 Composition/External 控制面。测试 Provider 只能位于 `teleoperation_support/system_tests/`。

## 后果

- 操作者可从目录名直接定位运行节点，非节点支撑不再与节点混排。
- package 名和 ROS wire contract 不变，因此下游命令与依赖方向无需迁移。
- 所有源码态脚本必须通过 Collection root 和显式 package-path 映射定位，不得依赖相邻包或 `parents[n]` 猜测。
- 旧 `src/collection/omni_hand/` 路径不保留符号链接或兼容壳；源码链接和工程文档必须同步更新。
- 架构测试阻断顶层 allowlist、错误 package owner、support 生产节点泄漏和 vendor 被 colcon 发现。
