# 组件与 ROS 图行为测试

更新时间：2026-08-14

## 文档职责

本文记录三个业务节点在公开 ROS seam 上的组件行为和局部 ROS 图测试：接收、重定向、控制。测试不调用节点私有算法，不把诊断状态 Topic 当作控制安全输入，也不把软件 Provider 测试误写成真机验证。

## 行为边界

```text
UDP JSON v3
    ↓ 真实 loopback ingress
rokoko_hand_receiver
    ↓ RawHandFrame
hand_retargeting
    ↓ JointState soft target
omnihand_o10_control
    ↓ final joint command
公开 Topic/Service + 确定性测试 Provider
```

节点边界和数据语义由 [模块边界与数据流](../01_知识/01_模块边界与数据流.md) 及 [架构文档](../01_知识/ARCHITECTURE.md) 负责；本文只记录如何观察和验收行为。

## T04：Rokoko 接收行为

测试入口：`rokoko_hand_receiver/test/test_scene_decoder.py`、`test_receiver_node.py`。

| 场景 | 期望行为 | 证据 |
| --- | --- | --- |
| 合法 JSON v3 + Actor | 按节点名重排为规范 21 节点并发布对应侧 RawHandFrame | 通过 |
| Actor 缺失或场景级非法 | 当前场景不向双侧发布 | 通过 |
| 单侧坏包/节点非法 | 丢弃该侧，合法另一侧继续发布 | 通过 |
| 双手同场景 | 两侧共享接收时间，但 Topic 和错误隔离 | 通过 |
| UDP loopback | 使用真实 datagram ingress，不建立第二套 decoder | 通过 |
| QoS | Reliable、Volatile、KeepLast(10) | 通过 |

包内 decoder/loopback/QoS 共 22 tests 通过。该证据只覆盖官方文档构造 fixture；真实 Rokoko Studio 脱敏抓包尚未提供，因此不写成现场兼容通过。

## T05：重定向组件与图行为

测试入口：`hand_retargeting/test/test_normalization.py`、`test_retargeting_node.py`。

测试观察 RawHandFrame 输入、RetargetingState 输出和软目标 Topic，覆盖：

- `INITIALIZING → COLLECTING_LENGTHS → WAITING_FIRST_VALID_IK` 的阶段推进；
- 五指冻结前无软目标，首次有效 IK 前不以默认姿态填补；
- 左右手可不同步且历史完全隔离；
- 掌坐标纵向/横向退化只暂停当前侧；
- 单指长度冻结异常只影响该指，模型错误进入 `MODEL_ERROR`；
- 单指 IK 失败保持该指上一有效结果，不污染其他手指。

当前 `hand_retargeting` 包级证据为 26 passed、1 skipped。skip 必须保持为环境或外部模型边界，不可改写成通过。

## T07：控制组件与图行为

测试入口：`omnihand_o10_control/test/` 及其 ROS 图 prior-art 测试。

| 能力 | 验收断言 |
| --- | --- |
| 直驱使能 | 每侧反馈、错误监控、目标就绪且目标新鲜时自动使能；任一无就绪或 stale 则 `VALID_MOTION_DISABLED`，不产生命令 |
| clear_fault | 幂等；失败不排队；成功需致命错误位清零、通信健康并重读真实位置；`4fedfaa` 起 arm/disarm 已移除 |
| stale | 同时检查上游输入年龄和本机接收间隔；二者均为显式必填配置；进入 `PAUSED_TARGET_STALE` |
| 故障 | 错误位、反馈/回读超时、非法反馈和重启/断连触发锁存；不自动恢复；`commu_except`(bit4) 不锁存 |
| 硬限速 | 使用真实反馈、本机单调时钟、单次额度封顶；无效目标不推进基准 |
| slew | 非发送事件的 `slew_limited` 全为 false；发送后才更新实际命令基准 |
| Provider | 软件 Provider 无厂商库、设备文件、CAN/USB 依赖，能确定性模拟反馈、错误和超时 |

控制包共 65 tests，ROS 图测试 6/6 通过。Adapter 只负责 wire schema 和结果码映射，不能在此处复制接口 numeric literal 或拥有控制状态。

## 公开观察原则

行为测试只通过公开 Topic、Service 和 loopback UDP 建立断言。状态 Topic 用于诊断和录制，不参与安全判定；测试不得通过私有 callback、内部字段或直接调用 Application 私有方法绕过公开 seam。

## 与其他测试文档的分界

- 字段、枚举、模型结构和真实梯度见 [接口、模型与算法契约测试](04_接口模型与算法契约测试.md)；
- 软件/生产 Provider、bringup、端到端图和架构依赖见 [系统集成与架构门禁测试](06_系统集成与架构门禁测试.md)；
- 全局计数及 T01–T11 状态见 [测试总览](03_测试总览与追踪矩阵.md)。
