# Probe Points（探针点定义）

本仓库验收证据围绕真实数据流采集。每个探针点定义：数据从哪里获取、数据类型、采集命令、保存格式、采样时间、如何与其他探针对齐。

数据流总览（全部来自当前仓库真实实现）：

```text
P0 UDP 输入（14043 / loopback / fixture）
 ↓
[rokoko_hand_receiver]          src/collection/omni_hand/rokoko_hand_receiver/
 ↓
P1 /rokoko/{left,right}/raw_hand            (rokoko_omnihand_msgs/msg/RawHandFrame)
 ↓
[hand_retargeting]              src/collection/omni_hand/hand_retargeting/
 ↓
P2 /hand_retargeting/{side}/state           (RetargetingState)
P3 /o10_control/{side}/command              (sensor_msgs/msg/JointState, 10 关节, 仅 ready 后发布)
 ↓
[omnihand_o10_control]          src/collection/omni_hand/omnihand_o10_control/
 ↓
P4 /o10/{side}/joint_cmd                     (JointState, 硬限速后)
   /o10_control/{side}/state                 (O10ControlState)
 ↓
[Provider: software_o10_provider / 生产 Agilink]
 ↓
P5 /o10/{side}/joint_states                  (JointState 反馈)
   /o10/{side}/joint_error_states            (std_msgs/msg/Int16MultiArray)
   /o10/{side}/read_active_joints            (ReadO10ActiveJoints srv)
   /o10/{side}/test_injection                (std_msgs/msg/String, 仅软件 Provider, 9 种故障注入)
 ↓
P6 MCAP 录制（外部 ros2 bag record --storage mcap）
```

## 对齐基础

- P1 `RawHandFrame.header.stamp` = receiver 收到 UDP 数据报的时刻（节点 ROS 时钟）。
- P3 `/o10_control/{side}/command` 的 `header.stamp` 继承上游 Raw 接收时间。
- P4 `/o10/{side}/joint_cmd` 保留上游 header.stamp。
- 因此 P1/P3/P4 可跨探针按 stamp 对齐；P2/P5 按各自消息时间戳或顺序号对齐。
- 录制统一使用一个 `ros2 bag record` 进程同时录制 P1–P5 的公开 topic（清单见下），保证同一时间基准。

## 各探针定义

### P0 — 输入源（刺激）

| 项 | 内容 |
| --- | --- |
| 来源 | ① 合成场景：`rokoko_omnihand_system_test/.../scenes.py::scene_payload()` 经 loopback UDP 发到 127.0.0.1:<free_port>（默认验收路径）；② 真实抓包 fixture：`rokoko_hand_receiver/test/fixtures/captured_left_glove_v3.lz4`；③ 真实 Rokoko Studio UDP 14043（人工 checkpoint） |
| 数据类型 | LZ4 压缩 JSON v3（version="3,0"，~2978B/帧，30fps） |
| 采集命令 | 无（刺激本身）；② 用 fixture 文件直接喂 decoder 或 replay |
| 保存格式 | 原样保存数据报/文件副本到 `artifacts/` |
| 对齐 | 记录发送时刻与场景内容（节点名/关节数/手指数量） |

### P1 — Receiver 输出

| 项 | 内容 |
| --- | --- |
| 数据来源 | `/rokoko/{left,right}/raw_hand`（Reliable/Volatile/KeepLast(10)） |
| 消息类型 | `rokoko_omnihand_msgs/msg/RawHandFrame`：`actor_index`、`actor_name`、`source_timestamp`、`string[21] node_names`、`geometry_msgs/Point[21] positions`、`geometry_msgs/Quaternion[21] orientations` |
| 采集命令 | `ros2 topic echo /rokoko/left/raw_hand --full`；录制：`ros2 bag record --storage mcap ...` |
| 保存格式 | topic echo 文本存 `artifacts/p1_*.txt` 或统一 bag |
| 采样时间 | 每帧（30fps 输入下约 33ms） |
| 对齐 | header.stamp = 接收时刻；frame_id = "rokoko_world_y_up_z_forward" |
| 辅助日志 | `"listening for Rokoko JSON v3 on {bind}:{port}; actor_index=..."`；`"dropped Rokoko {side} input ({count} occurrence(s)): {reason}"`（2 的幂次节流，receiver 节点日志） |

### P2 — Retargeting 状态

| 项 | 内容 |
| --- | --- |
| 数据来源 | `/hand_retargeting/{side}/state` |
| 消息类型 | `rokoko_omnihand_msgs/msg/RetargetingState`：phase 枚举（`PHASE_INITIALIZING=0 … PHASE_MODEL_ERROR=7`）、`LENGTH_*`、`IK_*`（含 `SOLVER_NOT_RUN=0`）、逐指 5 元数组 + 恢复计数/时长 |
| 采集命令 | `ros2 topic echo /hand_retargeting/right/state --full` |
| 保存格式 | topic echo 文本存 `artifacts/p2_*.txt` 或统一 bag |
| 采样时间 | 随输入帧推进（state 在每次处理后发布） |
| 对齐 | 记录 phase 转移时刻（如 collecting → waiting-first-valid-ik → tracking） |

### P3 — Retargeting 命令输出

| 项 | 内容 |
| --- | --- |
| 数据来源 | `/o10_control/{side}/command`（Reliable/Volatile/KeepLast(10)） |
| 消息类型 | `sensor_msgs/msg/JointState`：name=固定 10 个主动关节名、position=平滑后 rad、velocity/effort 空 |
| 关键事实 | **仅当 `command_published` 为真才发布**；缺失即表示按设计无 command（如不可达目标、length collecting 中） |
| 采集命令 | `ros2 topic echo /o10_control/right/command --full` |
| 保存格式 | topic echo 文本存 `artifacts/p3_*.txt` 或统一 bag |
| 对齐 | header.stamp 继承 P1 的接收时间 |

### P4 — 控制安全门输出

| 项 | 内容 |
| --- | --- |
| 数据来源 | `/o10/{side}/joint_cmd`；`/o10_control/{side}/state` |
| 消息类型 | `JointState`（仅 position）；`rokoko_omnihand_msgs/msg/O10ControlState`（`EVENT_* 0-7`、`PHASE_* 0-5`、`TARGET_* 0-9`、`FAULT_*` 位掩码、`bool[10] slew_limited`、`uint16[10] hardware_error_bits`、各关键时间戳+availability） |
| 采集命令 | `ros2 topic echo /o10/right/joint_cmd --full`；`ros2 topic echo /o10_control/right/state --full` |
| 保存格式 | topic echo 文本存 `artifacts/p4_*.txt` 或统一 bag |
| 对齐 | joint_cmd 保留上游 stamp；state 按消息时间戳 |
| 辅助观察 | Service `/o10_control/{side}/arm|disarm|clear_fault` 的同步响应（结果码 + 操作后状态快照） |

### P5 — Provider 边界（反馈）

| 项 | 内容 |
| --- | --- |
| 数据来源 | `/o10/{side}/joint_states`、`/o10/{side}/joint_error_states`；Service `/o10/{side}/read_active_joints` |
| 消息类型 | `JointState`；`std_msgs/msg/Int16MultiArray`（10 个错误字）；`ReadO10ActiveJoints.srv`（`READ_SUCCESS=0 … READ_INTERNAL_ERROR=4`、`float64[10] position`） |
| 故障注入 | `/o10/{side}/test_injection`（`std_msgs/msg/String`）：`healthy / error_bits / error_query_timeout / feedback_read_timeout / command_readback_timeout / invalid_feedback / invalid_error_status / disconnect / restart`（仅软件 Provider） |
| 采集命令 | `ros2 topic echo /o10/right/joint_states --full`；`ros2 service call /o10/right/read_active_joints rokoko_omnihand_msgs/srv/ReadO10ActiveJoints "{}"` |
| 保存格式 | topic echo/service 响应文本存 `artifacts/p5_*.txt` 或统一 bag |
| 对齐 | 与 P4 joint_cmd 的 readback 配对（命令回读一致性） |

### P6 — MCAP 录制（统一时间基准）

| 项 | 内容 |
| --- | --- |
| 数据来源 | 外部 `ros2 bag record --storage mcap` |
| 采集命令 | 录制 topic 清单（沿用 `test_t10_mcap.py` 已验证清单）：`/rokoko/right/raw_hand`、`/hand_retargeting/right/state`、`/o10_control/right/state`、`/o10/right/joint_cmd`、`/o10/right/joint_states`（左右侧同理） |
| 保存格式 | `.mcap` 文件存 `artifacts/`（原始 MCAP 不进 Git） |
| 采样时间 | 实验全程 |
| 对齐 | 同一 bag 内所有 topic 天然同时间基准，供 Analysis Agent 回放对齐 |

## 实验 harness 三档

- **A 档（默认，无真机）**：`RosGraph` 进程内组装真实 receiver + retargeter + control + software provider（`src/collection/omni_hand/rokoko_omnihand_system_test/rokoko_omnihand_system_test/graph.py::RosGraph`），输入走 loopback UDP（`scenes.py`），观察走公开 topic/service。参考其参数覆盖（`graph.py` 的 `_retarget_parameter_overrides()`、`_control_config()`）。
- **B 档（进程级）**：/tmp 独立 colcon 工作区 + `ros2 run` / `ros2 launch`。构建命令（含 Python 3.12 与 mamba 环境要求）见 `DOCS/03_工程/03_测试总览与追踪矩阵.md`。注意：`hand_retargeting_node` 需要 `DEXHIT_COLLECTION_PREFIX` 与 `OMNIHAND_O10_MODEL_FIXTURE`，缺失返回 BLOCKED_ENV。
- **C 档（真机，人工 checkpoint）**：生产 Provider（Agilink SDK）+ 真实 OmniHand O10 / 真实 Rokoko Studio。遵守 `编程执行规则` §10 验证阶梯；自动化结果不能替代人工确认。

## 采集纪律

- 每个实验至少采集：P0 刺激记录 + 观察目标所在探针点数据 + P6 bag（若涉及时序对齐）。
- 每条 raw 数据记录必须带：采集命令原文、时间、环境快照（git revision、env、参数覆盖）。
- 未采集到的数据写进 Missing Data，不得默认为"不存在"。
