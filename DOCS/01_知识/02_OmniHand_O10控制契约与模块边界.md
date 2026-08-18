# OmniHand O10 控制契约与模块边界

本页定义 OmniHand O10 在 `collection` 阶段中的稳定职责、控制契约和硬件边界。实现文件、构建命令、测试结果和一次性真机状态不属于本页。

## 状态口径

- **当前事实**：项目使用官方 ROS 2 驱动连接 OmniHand O10，并在上游设置独立的双手控制入口。
- **当前事实**：现有项目控制入口只做 10 维有限值与左右手限位校验，然后直接转发，尚未实现本文已经确认的最终关节变化率硬限制。
- **目标设计**：Rokoko 手套数据经过采集桥接和人体到机器人重定向后进入 O10 控制入口；控制入口以真实启动反馈初始化硬限制器，以事件触发方式产生有界变化命令；相关观测、目标和反馈最终进入 `raw MCAP`。
- **未知问题**：具体速度参数、启动反馈新鲜度阈值、stale 恢复状态机、最终 ROS 消息/QoS 和真机验收条件尚未形成稳定契约。

## 数据流与模块职责

```text
Rokoko Smartgloves
        ↓
rokoko_bridge_node
        ↓  规范化人体手部状态
hand_retargeting_node
        ↓  O10 主动关节目标
OmniHand O10 控制入口
        ↓  已校验的 JointState.position[10]
官方 omnihand_2025_node
        ↓  SDK / 设备通信
实体 O10 左手与右手
```

各模块职责：

| 模块                       | 拥有的职责                                            | 不负责                                 |
| -------------------------- | ----------------------------------------------------- | -------------------------------------- |
| `rokoko_bridge_node`     | 获取并规范化人体手部状态                              | O10 关节、限位、设备地址和 SDK         |
| `hand_retargeting_node`  | 将人体手部状态转换为 O10 主动关节目标                 | CAN、USB、官方 SDK 和实体手选择        |
| OmniHand O10 控制入口      | 校验左右手目标、施加最终变化率硬限制并转交官方驱动    | 人体动作解释、自然度平滑和硬件通信     |
| 官方`omnihand_2025_node` | ROS 消息到 SDK/设备通信的转换、逻辑手到实体设备的绑定 | Rokoko 解析和人体到机器人重定向        |

项目保留官方节点作为外部硬件 Adapter，不在控制入口中重新实现 CAN、串口、设备生命周期或 SDK 调用。这样把厂商变化集中在硬件侧，把人体动作和机器人控制语义保留在项目拥有的模块中。

## 双手位置命令契约

O10 有 10 个主动自由度和 6 个被动自由度。控制命令只包含 10 个主动关节目标；被动关节由机械结构和官方运动学处理，不作为独立命令发送。

| 项目           | 左手                           | 右手                           |
| -------------- | ------------------------------ | ------------------------------ |
| 上游目标 Topic | `/o10_control/left/command`  | `/o10_control/right/command` |
| 官方命令 Topic | `/o10/left/joint_cmd`        | `/o10/right/joint_cmd`       |
| 官方反馈 Topic | `/o10/left/joint_states`     | `/o10/right/joint_states`    |
| 消息类型       | `sensor_msgs/msg/JointState` | `sensor_msgs/msg/JointState` |
| 控制字段       | `name[0..9]`、`position[0..9]` | `name[0..9]`、`position[0..9]` |
| 单位           | rad                            | rad                            |

控制入口的字段语义：

- 上游 `name` 必须恰好包含本文主动关节表的 10 个规范语义名称且顺序一致；控制入口不得只按位置数组盲用数据。
- 上游 `position` 必须恰好包含 10 个有限浮点数，表示重定向软平滑目标，并全部落在对应侧关节范围内。
- 上游 `header.stamp` 必须继承触发该目标的 RawHandFrame 接收时间，`header.frame_id` 必须为空；控制入口保留 header 供数据年龄和延迟追踪。
- 上游 `velocity` 和 `effort` 必须为空。转交官方驱动时，`name`、`velocity` 和 `effort` 均为空，只有经过硬限速的 `position` 被发送。
- 左右手由 Topic 身份选择；消息本身不携带实体设备 ID。

## 主动关节顺序与范围

以下索引为 ROS 数组的零基索引，契约基于官方 OmniHand SDK 1.1.8。左右手屈伸和侧摆并非全部同号，上游不得把右手角度直接复制为左手角度。

| 索引 | 关节语义       | 右手范围 rad      | 左手范围 rad      |
| ---: | -------------- | ----------------- | ----------------- |
|    0 | `thumb_roll` | `[-0.03, 1.12]` | `[-1.12, 0.03]` |
|    1 | `thumb_abad` | `[-1.64, 0.05]` | `[-0.05, 1.64]` |
|    2 | `thumb_mcp`  | `[0, 0.8416]`   | `[-0.8416, 0]`  |
|    3 | `index_abad` | `[-0.16, 0]`    | `[0, 0.16]`     |
|    4 | `index_pip`  | `[0, 1.48]`     | `[0, 1.48]`     |
|    5 | `middle_pip` | `[0, 1.48]`     | `[0, 1.48]`     |
|    6 | `ring_abad`  | `[0, 0.17]`     | `[-0.17, 0]`    |
|    7 | `ring_pip`   | `[0, 1.48]`     | `[0, 1.48]`     |
|    8 | `pinky_abad` | `[0, 0.19]`     | `[-0.19, 0]`    |
|    9 | `pinky_pip`  | `[0, 1.48]`     | `[0, 1.48]`     |

## 重定向软目标与厂商命令语义

重定向节点继续使用标准 `sensor_msgs/msg/JointState`，不增加自定义 O10 目标消息：

```text
/o10_control/left/command
/o10_control/right/command
```

上游 `JointState` 契约为：

```text
header.stamp    = 触发本次计算的 RawHandFrame.header.stamp
header.frame_id = ""
name            = 固定 10 个主动关节语义名称
position        = q_soft[10]，单位 rad
velocity        = []
effort          = []
```

左右手共享名称语义与顺序，Topic 决定逻辑手侧以及对应符号和限位。重定向节点在未 armed 时仍可产生合法软目标用于诊断和外部录制；是否向实体手运动由控制入口的 `motionEnabled` 决定。

stale 恢复后的第一条软目标虽然数值等于 stale 前保持目标，但其 `header.stamp` 使用触发恢复成立的当前 RawHandFrame 接收时间，表示本次控制决策触发时刻。恢复过渡状态由诊断消息表达，不在关节命令中编码。

控制入口执行硬变化率限制后继续使用 `JointState` 发布厂商命令：

```text
/o10/left/joint_cmd
/o10/right/joint_cmd
```

其中 `position` 是 \(\mathbf q_s^{\mathrm{send}}\)，而不是 \(\mathbf q_s^{\mathrm{soft}}\)；header 保留上游目标 header，`name`、`velocity`、`effort` 为空。两级 Topic 必须均可由外部 rosbag2/MCAP 录制，以观测硬限制是否介入。

## 失败语义与运行边界

- 长度错误、NaN、无穷值或任一关节越界时，该手整帧被拒绝，不向官方命令 Topic 产生消息。
- 左右手是独立命令路径；一侧的非法帧不阻断另一侧的合法帧。
- 控制入口启动时不自动产生动作；每收到一帧合法上游目标，最多产生一帧经过硬限制的官方命令，不创建自主追赶旧目标的周期定时器。
- 上游停止发送后，控制入口保持静默。官方驱动或实体手如何处理最后目标仍是未知问题，不能假定存在 watchdog 或自动回零。
- 官方 `joint_states` 是位置命令触发后的回读，不承诺无命令时周期发布。消费者直接订阅官方反馈，控制入口不创建重复状态 Topic。
- 控制入口的硬限制只约束位置命令变化率，不提供周期轨迹插值、混合力控、触觉读取或硬件错误恢复。

## 显式控制使能

技术条件就绪不等于允许实体手运动。每个逻辑手侧独立维护操作者授权锁存：

\[
\operatorname{armed}_s\in\{\mathrm{false},\mathrm{true}\},
\qquad
\operatorname{armed}_s(\text{进程启动})=\mathrm{false}.
\]

定义以下由控制节点自行验证的瞬时前置条件：

- \(\operatorname{feedbackReady}_s\)：该侧硬限制器已经由新鲜、合法的真实启动反馈初始化；
- \(\operatorname{errorMonitorReady}_s\)：已获得当前有效的 O10 错误状态，且错误轮询未超时；
- \(\operatorname{targetReady}_s\)：本次控制进程中至少收到并验证过一条合法软目标；
- \(\operatorname{targetFresh}_s\)：最近合法软目标的上游时间及本机接收时间都未超过配置阈值；
- \(\operatorname{faultLatched}_s\)：该侧是否存在后续故障契约定义的锁存故障。

真正允许运动的派生条件为：

\[
\boxed{
\operatorname{motionEnabled}_s
\iff
\operatorname{armed}_s
\land\operatorname{feedbackReady}_s
\land\operatorname{errorMonitorReady}_s
\land\operatorname{targetReady}_s
\land\operatorname{targetFresh}_s
\land\neg\operatorname{faultLatched}_s
}
\]

控制节点不得订阅诊断用的 `RetargetingState` 来驱动安全门。`targetReady` 和 `targetFresh` 必须从控制节点实际收到的 `/o10_control/{side}/command` 及本地计时独立得出，使诊断消息丢失或延迟不会改变机械手运动。

使能必须来自操作者的显式单侧请求。请求到达时只有全部技术前置条件当前成立才可令 \(\operatorname{armed}_s\leftarrow\mathrm{true}\)；否则拒绝并报告原因。失败请求不得排队、缓存或在条件以后恢复时自动生效。使能成功本身不发送命令，必须等待下一条新鲜合法目标。

操作者可以随时解除单侧使能。解除后立即停止产生新的官方命令，但不自动张手、不自动回零、不继续追赶旧目标，也不等同于硬件急停或驱动断能；另一侧不受影响。

上游停止产生新鲜软目标时 \(\operatorname{targetFresh}_s=\mathrm{false}\)，从而暂停发送，但已经成功的 \(\operatorname{armed}_s\) 保持不变。只有上游完成后续定义的恢复过程、重新产生新鲜合法软目标并且操作者未解除使能时，才可通过有界过渡自动恢复；数据恢复本身不能创建或恢复一个已经为 false 的操作者授权。

控制状态由 `/o10_control/{side}/state` 的 `O10ControlState` 显式报告。操作者通过每侧独立的 `/o10_control/{side}/arm`、`disarm` 和 `clear_fault` Service 发起状态转换；三者共用 `ControlOperation` 请求—应答类型。三类操作的成功条件、幂等行为、拒绝码、原子性和硬限速器状态转换由操作接口契约固定。

## 临时暂停与锁存故障

每侧分别维护：

\[
\operatorname{faultLatched}_s\in\{\mathrm{false},\mathrm{true}\}.
\]

临时暂停表示当前缺少继续产生新命令的条件，但没有证据证明 O10 硬件安全状态已经不可信。下列情况属于临时暂停或局部保持，不置位 \(\operatorname{faultLatched}_s\)：

- Rokoko 输入 stale；
- 单帧人体掌坐标退化或整侧人体输入无效；
- 单指节点、冻结尺度或 IK 候选无效；
- 单条上游 O10 目标长度错误、非有限或越界。

临时暂停不自动清除已经成功的 \(\operatorname{armed}_s\)。整侧暂停时停止新命令并保持最后已发送目标；单指失败继续遵守重定向算法的最近有效目标保持语义。恢复是否成立以及有界过渡由 stale 恢复契约单独定义。

以下情况属于锁存故障：

1. 厂商 O10 `joint_error_states` 中任一关节的**致命错误位**（bit0 `stalled`、bit1 `overheat`、bit2 `over_current`、bit3 `motor_except`）非零。`commu_except`（bit4）是厂商定义的**历史通信异常标记**，官方 SDK 明确其不反映当前故障且不阻止厂商侧控制，故**不纳入锁存判定**；`hardware_error_bits` 仍保留原始错误字（含 bit4）用于诊断；
2. 控制入口发送位置命令后，在配置期限内没有收到该侧预期的 `joint_states` 回读；
3. 硬件反馈不是 10 维、包含非有限值、越过对应侧关节范围或身份不一致；
4. 单调时钟、限速结果、关节范围、命令状态/时间状态原子更新或硬限制器状态等控制安全不变量失效；
5. 控制入口、厂商硬件 Adapter 或对应设备连接重启、断开，致使先前的命令基准不再可信。

发生上述任一情况时原子执行：

\[
\boxed{
\operatorname{faultLatched}_s\leftarrow\mathrm{true},
\qquad
\operatorname{armed}_s\leftarrow\mathrm{false}
}
\]

并立即停止产生新的该侧官方命令。另一侧拥有独立状态，不受影响。

错误位恢复为零或通信重新出现均不能自动清除锁存。清除故障必须由操作者显式请求，并且同时满足：当前错误报告的**致命错误位**全部为零（`commu_except` 历史标记忽略）、通信健康、成功独立读取一帧新鲜合法的真实主动关节状态，并以该状态重新初始化硬限制器。完成后：

\[
\operatorname{faultLatched}_s\leftarrow\mathrm{false},
\qquad
\operatorname{armed}_s=\mathrm{false}.
\]

因此清除故障不等于重新使能；操作者必须另行请求使能。

厂商 O10 错误状态是触发式读取：必须向 `/o10/{side}/joint_error_cmd` 发送查询才得到一次 `/o10/{side}/joint_error_states`。正式实现必须在硬件 Adapter/控制安全边界确定主动轮询机制、频率和超时；不能因为默认没有错误状态消息就假定 \(\operatorname{errorMonitorReady}_s=\mathrm{true}\) 或 \(\operatorname{faultLatched}_s=\mathrm{false}\)。具体查询频率和超时值留待参数标定。

命令—反馈跟踪误差暂不作为锁存条件，因为现有证据尚未确认 `joint_states` 是独立实体测量还是设置命令后的回显。确认反馈物理语义后，才能另行定义跟踪误差和持续时间阈值。

## 最终关节变化率硬限制

本节是目标契约；当前控制入口尚未实现。令 \(m\in\mathbb N\) 为某侧控制入口收到的合法上游目标序号，令 \(j\in\{0,\ldots,9\}\) 为主动关节索引。定义：

- \(q^{\mathrm{soft}}_{s,j}[m]\)：重定向节点发送给控制入口的软平滑关节目标，单位 rad；
- \(q^{\mathrm{send}}_{s,j}[m]\)：控制入口实际发送给官方驱动的关节命令，单位 rad；
- \(t^{\mathrm{mono}}_s[m]\)：控制入口处理该合法目标时读取的本机单调时钟；
- \(\dot q^{\max}_{s,j}>0\)：该侧该关节允许的最大命令变化率，单位 rad/s；
- \(\Delta t^{\mathrm{credit}}_{\max}>0\)：单次更新最多允许累计的时间额度，单位 s。

相邻实际发送命令间隔及其有效额度定义为：

\[
\delta t_s[m]
=t^{\mathrm{mono}}_s[m]-t^{\mathrm{mono}}_s[m-1],
\qquad
\widehat{\delta t}_s[m]
=\min\left(\delta t_s[m],\Delta t^{\mathrm{credit}}_{\max}\right).
\]

正常更新要求两个单调时刻和 \(\delta t_s[m]\) 均有限，且 \(\delta t_s[m]>0\)。定义：

\[
\operatorname{clip}(x,a,b)
=\begin{cases}
a,&x<a,\\
x,&a\le x\le b,\\
b,&x>b.
\end{cases}
\]

最终命令逐关节计算为：

\[
\boxed{
q^{\mathrm{send}}_{s,j}[m]
=q^{\mathrm{send}}_{s,j}[m-1]
+\operatorname{clip}\left(
q^{\mathrm{soft}}_{s,j}[m]-q^{\mathrm{send}}_{s,j}[m-1],
-\dot q^{\max}_{s,j}\widehat{\delta t}_s[m],
+\dot q^{\max}_{s,j}\widehat{\delta t}_s[m]
\right)
}
\]

因此单次停顿不会积累无限移动额度。控制入口只在收到新鲜上游事件时向目标前进；上游停止时不得靠内部定时器继续追赶旧目标。

### 初始化与运行基准

每侧硬限制器必须先从硬件 Adapter 独立读取的一帧新鲜、合法、10 维真实主动关节反馈初始化：

\[
\boxed{
\mathbf q_s^{\mathrm{send}}[0]
=\mathbf q_s^{\mathrm{feedback,init}}
}
\]

该赋值只初始化内部状态，不发送命令。首个上游目标也必须从这个真实姿态开始接受同一硬限制。不得以零位、关节范围中点、首个上游目标或上次进程缓存代替真实反馈；缺少合格启动反馈时，该侧保持 `uninitialized` 并拒绝发送命令。

完成初始化后，硬限制始终以上一条**实际发送**命令为运行基准，不以可能存在通信延迟和测量噪声的最新反馈逐帧重置基准。反馈继续用于连接与硬件状态诊断；命令—反馈跟踪误差只有在厂商反馈物理语义确认后才能加入安全判据。

### 原子更新与失败语义

每侧一次目标处理顺序固定为：

1. 校验 `name` 恰好 10 项且逐项匹配规范表，`position` 恰好 10 个有限值且处于该侧主动关节范围，`velocity`、`effort` 为空，header 与消息年龄合法；
2. 校验硬限制器已经由合格真实反馈初始化，并校验该侧状态允许处理目标；
3. 读取单调时钟并校验时间间隔；
4. 计算变化率受限输出，并再次校验其有限性和关节范围；
5. 发布成功后，原子更新上一实际发送命令和单调时间基准。

任一步失败均不发布，也不推进命令或时间基准；另一侧独立运行，不受影响。

### 当前实现缺口

现有控制入口仍为校验后直通，没有上述状态和限速计算。现有厂商 ROS 节点只保证 `joint_cmd` 触发一次 `joint_states` 回读，不提供已确认的“无动作启动读取”ROS 接口；但本地 SDK 1.1.8 动态库暴露 `GetAllActiveJointAngles()`。正式实现前必须在官方硬件 Adapter 边界补充独立启动读取能力，同时保持三节点系统边界不变。若该能力无法实现，不能降级为猜测初始姿态，该侧必须保持不可控制。

## 逻辑手与实体设备

O10 控制层只认识逻辑侧别 `left` 和 `right`。官方驱动配置负责把逻辑侧别绑定到实体设备，其选择依据可以包括连接类型、适配器、通道、串口路径和手设备 ID。

因此：

- 重定向和控制逻辑不得依赖 CAN 通道、USB 路径或设备序列号。
- 更换通信方式或设备地址不改变上游关节命令契约。
- 多对手的多实例部署尚未验证，不属于当前稳定项目事实。

## collection 记录边界

目标数据链应能够同时追踪人体手部状态、重定向后的 O10 目标和官方关节反馈，并最终写入不可被下游覆盖的 `raw MCAP`。具体消息 schema、时间同步方式和录制入口尚未定义，不能据此声称 O10 数据采集链已经完成。
