# Teleoperation Support

`teleoperation_support/` 是源码组织容器，不是 ROS/Python package，也不提供公共 import。它集中存放消息契约、模型资产、bringup 和测试支撑，避免这些非生产节点包与顶层长驻节点混排。

| 物理目录 | ROS package | 职责 |
| --- | --- | --- |
| `ros_interfaces/` | `rokoko_omnihand_msgs` | ROS 消息与服务 schema |
| `o10_contracts/` | `omnihand_o10_contracts` | O10 主动关节和共享契约 |
| `o10_model_assets/` | `omnihand_o10_model` | 模型资产加载边界 |
| `production_bringup/` | `rokoko_omnihand_bringup` | 生产组合、参数和启动实现 |
| `system_tests/` | `rokoko_omnihand_system_test` | 系统测试与测试 Provider |
| `architecture_tests/` | `rokoko_omnihand_architecture_test` | 依赖和目录架构门禁 |

此目录不得演变成 `common/`、`utils/` 或跨包内部 API 汇聚点。唯一允许的非生产节点 executable 是 `system_tests/` 中的 `software_o10_provider`。
