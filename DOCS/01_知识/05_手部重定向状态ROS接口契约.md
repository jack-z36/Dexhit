# 手部重定向状态 ROS 接口契约

本文固定 Phase 1 手部重定向节点的可观测状态消息。状态只用于诊断、MCAP 录制和验收，不参与 O10 控制；状态消息丢失不得改变机械手运动。

## 消息与 Topic

```text
rokoko_omnihand_msgs/msg/RetargetingState

/hand_retargeting/left/state
/hand_retargeting/right/state
```

消息字段固定为：

```ros
std_msgs/Header header

string side

builtin_interfaces/Time input_stamp
bool solve_executed
builtin_interfaces/Time solve_finished_stamp
float64 solve_duration_sec

uint8 phase
bool ready
bool stale
bool command_published

uint8[5] length_state
uint8[5] ik_state

bool[5] has_valid_ik
bool[5] used_previous_valid_target

bool[5] residual_available
float64[5] normalized_residual

int32[5] solver_result_code
uint32[5] solver_evaluations

uint32 recovery_valid_count
float64 recovery_valid_duration_sec
```

五指数组顺序固定为：

```text
0 thumb
1 index
2 middle
3 ring
4 little
```

`side` 只能是 `left` 或 `right`，且必须与 Topic 身份一致。保留该字段是为了让 MCAP 导出或脱离 Topic 的状态仍然自解释。

## 时间语义

`header.stamp` 是本条状态快照实际发布时的 ROS 时间，`header.frame_id` 为空。状态既可由 RawHandFrame 处理触发，也可由 stale 定时检查或模型阶段转换触发，因此不得把它等同于输入时间。

`input_stamp` 是当前状态关联的最近一帧 RawHandFrame 接收时间。正常逐帧处理时等于该帧 `header.stamp`；stale 定时事件中仍保留最后输入时间。尚未收到任何输入时，由整体 `phase` 表明未初始化，零时间不得被解释成真实输入时间。

`solve_executed` 明确表示本事件是否运行了 IK。为 true 时，`solve_finished_stamp` 是本次同侧 IK 处理完成的 ROS 时间，`solve_duration_sec` 是本次同侧 IK 的实际耗时。为 false 时，消费者不得使用 `solve_finished_stamp`，且 `solve_duration_sec` 必须为 NaN，不能用 0 冒充“未求解”。

## 整体阶段

消息定义以下常量：

```ros
uint8 PHASE_INITIALIZING=0
uint8 PHASE_COLLECTING_LENGTHS=1
uint8 PHASE_WAITING_FIRST_VALID_IK=2
uint8 PHASE_TRACKING=3
uint8 PHASE_STALE=4
uint8 PHASE_RECOVERY_CONFIRMING=5
uint8 PHASE_RECOVERY_RESUMING=6
uint8 PHASE_MODEL_ERROR=7
```

`phase` 的语义为：

| 值 | 含义 |
| --- | --- |
| `INITIALIZING` | 正在加载和验证 URDF、MJCF、耦合与参数 |
| `COLLECTING_LENGTHS` | 至少一指人体长度尚未冻结 |
| `WAITING_FIRST_VALID_IK` | 五指长度已冻结，但至少一指尚无首次有效 IK |
| `TRACKING` | 正常处理实时 IK 与软目标 |
| `STALE` | 输入过期，停止发布目标 |
| `RECOVERY_CONFIRMING` | 正在累计连续整侧有效恢复帧 |
| `RECOVERY_RESUMING` | 恢复已确认，正在执行保持目标首帧和有界恢复 |
| `MODEL_ERROR` | 模型、资产或耦合校验失败，不能进入重定向 |

该阶段只描述重定向节点，不编码控制节点的 `armed`、`faultLatched` 或 `motionEnabled`。

## 整侧布尔状态

`ready` 严格使用算法基线定义：五指长度均已冻结，且五指都至少产生过一次有效 IK。它是历史就绪条件，不表示本事件发布了命令。

`stale` 表示同侧输入当前是否超过 stale 阈值。

`command_published` 表示处理本事件时是否向 `/o10_control/{side}/command` 发布了新软目标。以下组合均合法：

| 场景 | `ready` | `command_published` |
| --- | ---: | ---: |
| 尚未首次就绪 | false | false |
| 正常跟踪 | true | true |
| 整侧掌坐标无效 | true | false |
| stale 或恢复确认 | true | false |
| 单指失败且已有历史目标 | true | true |

## 五指长度状态

```ros
uint8 LENGTH_COLLECTING=0
uint8 LENGTH_FROZEN=1
uint8 LENGTH_CURRENT_INVALID=2
```

- `COLLECTING`：尚未冻结；当前坏样本只是不推进窗口。
- `FROZEN`：已经冻结且当前帧长度检查合法。
- `CURRENT_INVALID`：已经冻结，但当前节点或链长违反冻结尺度；冻结值不改变。

冻结前的坏样本仍报告 `COLLECTING`，因为尚不存在冻结基准。

## 五指 IK 状态

```ros
uint8 IK_UNINITIALIZED=0
uint8 IK_VALID=1
uint8 IK_INPUT_INVALID=2
uint8 IK_SIDE_INVALID=3
uint8 IK_RESIDUAL_EXCEEDED=4
uint8 IK_SOLVER_ERROR=5
uint8 IK_NOT_RUN_LENGTH_COLLECTING=6
uint8 IK_NOT_RUN_STALE=7
```

| 状态 | 含义 |
| --- | --- |
| `UNINITIALIZED` | 尚未获得任何可评估机会 |
| `VALID` | 当前 IK 候选通过完整有效性判定 |
| `INPUT_INVALID` | 当前单指节点或冻结长度无效 |
| `SIDE_INVALID` | 当前掌坐标退化，整侧没有求解 |
| `RESIDUAL_EXCEEDED` | 候选有限且合法，但归一化残差超标 |
| `SOLVER_ERROR` | 求解器异常、候选非有限或完整状态非法 |
| `NOT_RUN_LENGTH_COLLECTING` | 五指长度尚未全部冻结，未运行 IK |
| `NOT_RUN_STALE` | 当前处于 stale，未运行正常 IK |

恢复确认期间仍执行 IK，各指报告实际结果；恢复整体语义由 `phase` 表达。

## 历史目标与残差

`has_valid_ik[i]` 表示截至本事件，该指是否至少成功过一次。

`used_previous_valid_target[i]` 表示本次组合 10 维目标时，该指是否因当前失败使用了历史有效目标。它只表达组合决策；若 `command_published=false`，不声称该目标已发送。

当本次存在可评估候选时：

```text
residual_available[i] = true
normalized_residual[i] = 当前无量纲残差 eta
```

当未运行 IK 或异常导致残差不可计算时：

```text
residual_available[i] = false
normalized_residual[i] = NaN
```

消费者必须先检查可用位；禁止用数值 0 表示残差缺失，因为 0 代表零指尖误差。

## 求解器状态

`solver_result_code[i]` 保留 NLopt 原始返回码。项目保留：

```text
SOLVER_NOT_RUN = 0
```

表示本事件没有运行该指求解器；NLopt 成功码为正、失败码为负。返回码只描述求解器停止原因，不等于 IK 候选有效性。

`solver_evaluations[i]` 是该指本次目标/梯度评估次数；未运行时为 0。

## stale 恢复进度

`recovery_valid_count` 和 `recovery_valid_duration_sec` 仅在 `PHASE_RECOVERY_CONFIRMING` 中表示当前连续恢复序列。其他阶段二者均为 0。

## 发布规则

状态采用事件驱动发布，至少覆盖：

- 每次收到并处理一侧 RawHandFrame；
- 进入 stale；
- stale 恢复阶段转换；
- 模型初始化完成或失败；
- 参数变更导致整体阶段变化。

不要求固定周期重复完全相同的状态。监控方根据 `header.stamp` 判断状态消息本身是否过旧。两个状态 Topic 必须可由外部 rosbag2/MCAP 录制；重定向节点不直接写 MCAP。
