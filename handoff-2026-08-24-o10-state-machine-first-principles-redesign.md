# O10 状态机第一性原理重设计交接

## 当前状态

第一版极简状态机已经完成代码修改和 O10 控制包回归，当前等待用户审查。

本轮只修改 O10 状态机内部的 3 个源码文件及其 3 个单元测试文件；没有修改 ROS Node、消息、公共契约、硬件 Adapter、bringup、配置或项目知识文档，也没有启动控制链或操作真实硬件。

## 用户目标与表达偏好

- 当前只关注消费 `/o10_control/left/command` 的 O10 状态机。
- 用户把状态机理解为分类器：输入范畴 A 是所有控制指令，范畴 B 是允许执行的安全子集。
- 用户追求第一性原理、奥卡姆剃刀和低延迟。
- 用户不希望一次获得过多细节；后续优先用一个表格或一层 ASCII 图解释一个问题。
- 用户特别反对将频繁硬件查询、单次查询超时或消息年龄作为每帧指令放行条件，因为这会增加延迟并导致控制中途锁定。

## 已落实的第一性原理

> O10 状态机是一个实时安全分类器与投影器：在已有可信控制基准时，对最新的 10 维软目标进行纯计算；明显非法的当前帧直接丢弃，变化过大的目标投影成最大安全一步，只有明确会损坏硬件的四类致命错误才锁存故障。

控制快路径现在遵循：

```text
/o10_control/left/command
          │
          ▼
  能否解析完整10关节？ ──否──> 丢当前帧
          │是
          ▼
  数值有限且在硬限位？ ──否──> 丢当前帧
          │是
          ▼
     已有可信基准？     ──否──> 保持 SYNCING，不发送
          │是
          ▼
       变化率投影
          │
          ▼
       发布最终命令
```

快路径不查询 Service、不等待 `joint_states`、不等待错误查询，也不根据时间戳年龄决定是否放行。

## 已实现的范畴 B

| 限制因素 | 当前允许条件 | 不满足时的处理 |
| --- | --- | --- |
| 控制基准 | 状态为 `RUNNING`，保存上一条成功发送命令或合法反馈基准 | 不发送，保持 `SYNCING` 或原模式 |
| 手侧 | 指令侧与当前 ControlSession 侧一致 | 丢当前帧，不锁存 |
| 关节身份 | 恰好包含 10 个完整、唯一的主动关节名 | 丢当前帧，不锁存 |
| 关节顺序 | 输入顺序任意 | 按关节名重排成契约顺序 |
| 位置维数 | 能解析出 10 个位置 | 丢当前帧，不锁存 |
| 数值有效性 | 全部位置是有限数值 | 丢当前帧，不锁存 |
| 绝对限位 | 全部位置处于共享 URDF/合同硬限位内 | 丢当前帧，不锁存 |
| 变化率 | 最终发送命令不超过配置的单关节变化率 | 不拒绝目标，投影成当前最大安全一步 |
| 致命硬件错误 | 错误字 bit0-bit3 均未置位 | bit0-bit3 任一置位则进入 `FAULTED` |

以下因素已经移出每帧放行条件：

- `target_fresh` 和输入消息年龄；
- `error_monitor_ready`；
- 每条命令后的 `joint_states` 回读；
- 命令回读、Provider heartbeat、错误查询的单次超时；
- `ACTIVE/IDLE/PAUSED` phase；
- `velocity`、`effort`、`frame_id`；
- 输入关节必须严格按固定顺序排列的要求。

## 最小业务状态

`ControlSession` 现在只有一个可变业务状态 `_state`，类型为以下三者之一：

```text
_state
├── SYNCING
│   没有可信控制基准，不发送目标
├── RUNNING(base_position[10], base_monotonic)
│   使用明确基准执行纯变化率投影
└── FAULTED(reason)
    仅由明确的致命硬件错误进入
```

状态转换：

| 当前事件 | 转换结果 |
| --- | --- |
| 启动 | `SYNCING` |
| `SYNCING` 收到合法反馈/读取结果 | `RUNNING(feedback, now)` |
| `RUNNING` 成功发送命令 | 更新 `RUNNING(command, now)` 基准 |
| 命令发布失败 | `SYNCING` |
| `SYNCING` 后收到新合法反馈 | 自动恢复 `RUNNING` |
| 错误 bit0 堵转、bit1 过热、bit2 过流、bit3 电机异常 | `FAULTED(HARDWARE_ERROR)` |
| bit4 历史通信标记 | 不锁存，不改变业务状态 |
| 未定义错误位 | 不锁存，不改变业务状态 |
| 非法目标、零/负时间间隔、异常发送回调 | 丢当前帧或发布诊断，不锁存 |
| 单次读取、错误查询、heartbeat、命令回读超时 | 不锁存，不阻断后续合法目标 |

诊断快照和慢速查询协议仍因冻结的 ROS 公共接口而保留，但它们不参与目标快路径的通行判断。

## 实际代码修改范围

仅以下 6 个代码/测试文件被修改：

| 文件 | 修改内容 |
| --- | --- |
| `src/collection/omni_hand/omnihand_o10_control/omnihand_o10_control/application/control_session.py` | 用 `SYNCING/RUNNING/FAULTED` 取代冗杂业务布尔状态；快慢路径解耦；只有 bit0-bit3 锁存 |
| `src/collection/omni_hand/omnihand_o10_control/omnihand_o10_control/core/soft_target.py` | 放宽为按名称规范化、10 维、有限值和硬限位校验；忽略时间年龄及辅助字段 |
| `src/collection/omni_hand/omnihand_o10_control/omnihand_o10_control/core/slew_limiter.py` | 新增使用显式运行基准的纯函数 `project_slew()`；保留原 `SlewLimiter` 公共类兼容性 |
| `src/collection/omni_hand/omnihand_o10_control/test/test_control_session.py` | 固定三态转换、非锁存超时、明确致命错误、同步恢复和异常帧丢弃行为 |
| `src/collection/omni_hand/omnihand_o10_control/test/test_soft_target.py` | 固定宽松范畴 B：关节重排、时间戳诊断化、忽略辅助字段 |
| `src/collection/omni_hand/omnihand_o10_control/test/test_slew_limiter.py` | 固定纯投影函数只依赖显式 `RUNNING` 基准 |

明确没有修改：

- `node.py`；
- `contracts.py`；
- ROS 消息和 Service 定义；
- 硬件 Adapter；
- bringup、启动脚本和参数配置；
- `DOCS/01_知识`、`DOCS/02_约束`、`DOCS/03_工程`；
- 右手或其他遥操作模块。

本 handoff 文件的更新是用户在代码实现后单独授权的交接维护，不改变上述代码白名单。

## 验证证据

### O10 控制包

在 ROS Jazzy 环境和系统 Python 下执行：

```bash
set +u
source /opt/ros/jazzy/setup.bash
source install/setup.bash
/usr/bin/python3 -m pytest -q \
  src/collection/omni_hand/omnihand_o10_control/test
```

结果：

```text
72 passed in 4.59s
```

这 72 项包括纯状态机、软目标、限速器、冻结 Node 兼容和响应预算测试。

额外检查：

| 检查 | 结果 |
| --- | --- |
| `git diff --check` | PASS |
| `flake8 --select=F` 针对 6 个白名单文件 | PASS |
| Git 修改文件白名单 | PASS，恰好 6 个代码/测试文件 |
| ROS 节点启动 | 未执行 |
| 命令发布/arm/clear_fault | 未执行 |
| 真实 O10 运动 | 未执行 |

完整 `flake8` 仍会报告该包未统一遵循的 docstring、单引号和 79 列风格项；没有为处理这些非功能风格项扩大本次重构噪声。

### 强制预检基线

代码修改前已执行：

```bash
bash src/collection/omni_hand/init.sh
```

预检没有启动节点或硬件，但仓库原有基线未全绿：共收集 377 项测试，存在 6 个失败、2 个跳过。已观察失败均在本次白名单之外：

- `rokoko_hand_receiver` PEP257：1 项；
- 架构 A16 enum gate：1 项；
- system test 缺少 `pinocchio`：4 项。

因此只能确认 O10 控制包和本轮改动通过，不能声称整个仓库测试全绿。

## 当前仍未验证或存在的 Delta

1. **没有真机性能证据**：尚未测量 `/o10_control/left/command` 到 `/o10/left/joint_cmd` 的 p99 延迟，也没有证明实体手端到端小于 50 ms。
2. **没有硬件运动证据**：没有启动 Provider、没有发布命令、没有清故障、没有驱动实体手。
3. **最大变化率没有重新标定**：实现继续使用冻结配置中的 `max_joint_rates`，其真实安全性和跟随效果仍需厂商资料或受控真机标定。
4. **知识文档尚未同步**：现有 doc02/doc06/doc07 和部分架构测试仍描述旧的 freshness、error monitor、timeout 锁存语义。用户先前要求代码范围锁在状态机内部，因此本轮没有更新这些文档或契约。
5. **慢路径总线争用未做运行测量**：错误查询不再决定快路径是否通行，但 SDK/CAN 串行执行时是否仍与命令发送争用，需要后续性能诊断。
6. **明确断连语义仍未新增**：当前发布失败会进入 `SYNCING`；单次 heartbeat/read/query 超时不会锁存。更强的“确认断连”判据需要另行设计，不能擅自恢复旧式超时锁死。

## 建议下一步

下一位 Agent 不应立即继续扩大实现。应先向用户提交以下审查重点：

| 审查项 | 用户需要确认的内容 |
| --- | --- |
| 范畴 B | 当前只保留 10 关节解析、有限值、硬限位、可信基准和变化率投影是否足够 |
| 故障边界 | 是否确认只有 bit0-bit3 可以锁存 `FAULTED` |
| 未知错误位 | 是否确认未知位按诊断处理，而不是保守锁存 |
| 时间语义 | 是否确认旧时间戳和单次查询超时永不阻断快路径 |
| 文档 Delta | 审核代码后是否授权单独更新 doc02/doc06/doc07 与架构测试 |
| 性能验收 | 是否进入无硬件 ROS 延迟测量，再决定是否进行人工确认的真机步骤 |

只有用户确认代码语义并扩大范围后，才可更新冻结契约、知识文档、架构测试或运行配置。

## 工作区与安全提醒

- 当前 worktree 的 6 个代码/测试修改均未提交、未暂存。
- 本 handoff 文件仍是根目录未跟踪文件。
- 不得清理、覆盖、暂存或提交用户未授权的其他变更。
- 涉及 Rokoko/O10 的后续正式执行仍须先运行 `bash src/collection/omni_hand/init.sh`。
- 真正启动遥操作只能在预检通过并获得当前步骤人工确认后使用根入口 `./start_omnihand_control.sh`。
- 本交接不授权启动、发布、清故障、arm 或驱动真实硬件。
