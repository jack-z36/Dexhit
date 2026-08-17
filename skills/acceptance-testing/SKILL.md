---
name: acceptance-testing
description: "对已完成第一版开发的程序执行基于真实运行证据的 AI 验收测试：运行真实程序、采集原始 Evidence、沿真实数据流分析理想与现实差异、定位 Root Cause、制定并执行修复，然后强制重新进入验收循环直到复验通过。用户要求验收 / acceptance、要求验证已实现功能是否真正符合 Spec（不是只看代码），或要求 AI 运行程序采集运行证据时使用。不适用于开发阶段的 TDD、单元测试生成或普通代码审查。"
---

# Acceptance Testing（AI 验收测试工作流）

本 Skill 是项目专用验收 Multi-Agent Workflow 的唯一主入口。它教 Main Agent（编排者）**什么时候调用哪个 Subagent、如何在四个 Subagent 之间传递信息**，而不是让编排者自己代替它们完成核心工作。

> **第一版程序开发完成后，由 AI 运行真实程序、采集客观运行证据、分析理想状态与现实状态的差异、定位原因、制定优化方案并执行修复，随后重新进入验收循环。**

## 1. 核心铁律

```text
Experiment    = What happened?
Analysis      = Why did it happen?
Solution      = What should change?
Execution     = Make the requested change.
Revalidation  = Did reality now match the expected state?
```

四者职责不得混合。以下等式不成立：

```text
没有测试 ≠ PASS
没有观察到异常 ≠ 证明正确
Execution 完成 ≠ 验收完成
Analysis 的猜测 ≠ Root Cause
Root Cause ≠ Solution
Solution ≠ Implementation
Implementation ≠ Verified Fix
```

## 2. 与已有 Skill 的关系（不重叠）

- `/dispatch-tickets`：派发纪律与上下文切片方法复用（`fork_context=false`、message 自包含、必填回复契约）；本 Skill 的 Execution Agent 单任务内部遵守 `/implement` + `/tdd`。
- `/code-review`：验收流程结束后可选的集成代码审查门禁，不是验收本身。
- `/diagnosing-bugs`：面向单个 bug 的调试循环；本 Skill 的 Analysis Agent 借用其"可证伪假设 + 证据不足不许猜"方法，但覆盖范围是整条验收数据流。
- `/to-spec`、`/to-tickets`：上游；本 Skill 不重新定义需求、不重新拆票。
- 不重复创建任何新角色类 Skill：四个 Subagent 的角色契约都在本 Skill 目录内。

## 3. 状态机

```text
Human Acceptance Goal
        │
        ▼
PLANNING ──────────────┐
        │              │（编排者建 run、manifest、首个 Experiment Request）
        ▼              │
EXPERIMENTING          │
        │              │
        ▼              │
ANALYZING ─────────────┤
        │              │
        ├─ 证据不足 ──► NEED_MORE_EVIDENCE ──►（新 Experiment Request）──► EXPERIMENTING（≤3 轮）
        │              │
        ├─ 无缺陷 ────► VERIFIED_PASS（终局）
        │              │
        ▼              │
ROOT_CAUSE_CONFIRMED   │
        │              │
        ▼              │
SOLUTION_PLANNING      │
        │              │
        ▼              │
EXECUTING ─────────────┤（每 task 一个 Execution Agent，单 task 修复 ≤3 轮）
        │              │
        ▼              │
REVALIDATING ──────────┘（强制重新 EXPERIMENTING → ANALYZING；整循环 ≤3 次，超限人工）
        │
        ├─ 通过 ──► VERIFIED_PASS ──► FINAL_REPORT
        └─ 失败 ──► VERIFIED_FAIL ──► FINAL_REPORT（或回 SOLUTION_PLANNING 重新设计）
```

状态定义：

| 状态 | 含义 | 进入条件 | 离开条件 |
| --- | --- | --- | --- |
| PLANNING | 编排者读取上下文、创建 run 目录与 manifest、把验收目标转成第一个 Experiment Request | 工作流启动 | 首个 request 校验通过 → EXPERIMENTING |
| EXPERIMENTING | Experiment Agent 执行实验并产出 Raw Experiment Report | 收到 Experiment Request | raw-report 通过编排者校验 → ANALYZING |
| ANALYZING | Analysis Agent 对照 Spec 预期沿数据流找 First Divergence | 本次分析所需 raw-report 全部到齐 | 证据不足 → NEED_MORE_EVIDENCE；确认缺陷 → ROOT_CAUSE_CONFIRMED；无缺陷且全部预期复验 → VERIFIED_PASS |
| NEED_MORE_EVIDENCE | Analysis 生成补充 Experiment Request（明确要什么数据、在哪观察、施加什么刺激、为什么、能区分哪些 competing hypotheses） | Analysis 判定证据不足 | 新 request 校验通过 → EXPERIMENTING |
| ROOT_CAUSE_CONFIRMED | Investigation Report 通过编排者校验（FACT/INFERENCE/HYPOTHESIS 严格区分、每条结论有 evidence 引用） | Analysis 证据充分 | → SOLUTION_PLANNING |
| SOLUTION_PLANNING | Solution Agent 产出 Solution Proposal 与 Micro Tasks | Investigation Report 通过 | 方案与 tasks 校验通过 → EXECUTING |
| EXECUTING | 逐 task 派发 Execution Agent；每 task 最多 3 轮 execute-review | tasks 批准 | 全部 task 完成（含 BLOCKED 记录）→ REVALIDATING |
| REVALIDATING | 强制重新进入 EXPERIMENTING → ANALYZING，对修复后的现实重新验收 | 全部 task 完成 | 复验通过 → VERIFIED_PASS；复验失败且循环未耗尽 → SOLUTION_PLANNING；耗尽 → 人工 checkpoint |
| VERIFIED_PASS | 理想状态与复验后现实一致 | REVALIDATING 通过 | → FINAL_REPORT |
| VERIFIED_FAIL | 确认 divergence 且修复循环耗尽仍未复验通过 | REVALIDATING 失败且循环耗尽 | → FINAL_REPORT |
| NOT_VERIFIED / EVIDENCE_INSUFFICIENT / BLOCKED / OUT_OF_SCOPE | 见 §12 终态定义 | 对应停止条件 | → FINAL_REPORT |

循环预算（硬上限，超限即停并人工 checkpoint）：

1. 每次 ANALYZING 的补充实验 ≤ **3 轮**；
2. 每个 Micro Task 的 execute-review ≤ **3 轮**；
3. 整条 SOLUTION → EXECUTION → REVALIDATING 失败循环 ≤ **3 次**。

## 4. 四个 Subagent 角色与 I/O 契约

完整派发 prompt 模板见 `skills/acceptance-testing/references/agent-roles.md`；报告模板见 `skills/acceptance-testing/references/report-templates.md`。以下为不可协商契约：

### 4.1 Experiment Agent（实验执行器 / 智能测量仪器）

只回答 **What happened**。负责：运行程序、施加输入、采集数据、记录环境、保存 Evidence。

- 输入：`runs/acceptance/<run-id>/experiments/EXP-nnn/request.md`（Experiment Request）。
- 输出：`.../EXP-nnn/raw-report.md`（Raw Experiment Report）+ `.../EXP-nnn/artifacts/` 原始采集物。
- 允许：执行测试与采集命令（ROS 节点、topic echo、bag record、colcon test），写入 `runs/acceptance/<run-id>/` 与系统临时目录。
- 禁止：修改任何生产代码（`src/`、`DOCS/`、`skills/`、测试源码）；提出解决方案；猜测 Root Cause；挑选证据支持自己的观点；把缺失信息解释为正常；把"没观察到"解释为"不存在"；因果或意图判断。

允许的报告语句：`14.25 秒以后未观察到新的 command`、`solver_result = -5`、`phase 在 21.3 秒时从 PHASE_LENGTH_COLLECTING 进入 PHASE_WAITING_FIRST_VALID_IK`。
禁止的报告语句（除非是程序公开输出的原始字符串）：`stale 逻辑出现 Bug`、`IK 求解器失败`、`原因应该是……`。

### 4.2 Analysis Agent（复杂推理主体）

只回答 **Why did it happen**。负责：Expected vs Observed → 数据流 → Hypothesis → Evidence → Root Cause。

- 输入：Spec 预期（`DOCS/03_工程/01_...Spec.md`）、全部 Raw Experiment Report、必要的代码与架构上下文（ARCHITECTURE、ADR、相关源码）。
- 输出：`.../investigation/report.md`（Investigation Report），或当证据不足时输出一个新的 Experiment Request（写入 `experiments/EXP-nnn/request.md` 并返回 NEED_MORE_EVIDENCE）。
- 方法：沿真实数据流逐级（P0→P6，见 `references/probe-points.md`）寻找 **First Divergence**，即理想状态与现实状态第一次发生偏离的位置；对每条结论生成可证伪假设并用现有 evidence 检验；证据不足时绝对禁止"很可能是 XXX，所以建议修改 XXX"，必须申请补充实验并说明该实验能区分哪些 competing hypotheses。
- 禁止：在 evidence 不足时下结论；直接跳到方案；修改任何文件（只读代码）。

### 4.3 Solution Agent（方案规划）

不重新调查"为什么出错"，相信 Investigation Report。只回答 **What should change**。

- 输入：Investigation Report、当前代码库、ARCHITECTURE、ADR、相关约束与 Skill。
- 输出：`.../solution/solution.md`（Solution Proposal）+ `.../solution/tasks/TASK-nnn.md`（Micro Tasks）。
- Micro Task 要求：单一目标、范围小到一个 Agent Context 可完成、明确 Allowed/Forbidden Scope、明确输入输出、明确完成条件与验证方式。
- 禁止：在没有证据的情况下重新定义 Root Cause；偷偷扩大功能 Scope；把大型模糊工作扔给 Executor；直接修改生产代码。

### 4.4 Execution Agent（施工）

只做 **Make the requested change**。

- 输入：单个 Micro Task + 完成该任务所需的最小上下文。
- 流程：Read Task → Inspect Relevant Code → Implement → Run Developer-level Verification → Return Report。
- 输出：`.../execution/TASK-nnn-report.md`（Execution Report）。
- 遇到 Task 矛盾、架构冲突、缺少关键输入、Scope 无法满足 → 停止并返回 **BLOCKED**，不得自行重新设计方案。
- 禁止：擅自扩大修改范围；顺手重构无关模块；重新解释 Root Cause；宣称整个问题已解决；宣称验收 PASS。最多只能说 "Micro Task implemented successfully."，然后系统必须重新进入 Experiment Agent。

## 5. Dispatch 规则（编排者）

1. 主派发路径：用 `skills/acceptance-testing/references/agent-roles.md` 的模板组装完整 message，通过 Codex `multi_agent_v1__spawn_agent`（`fork_context=false`，子代理零上下文继承）或本环境可用的 Agent 派发工具发出。
2. 每次 spawn **必须**显式指定 `model` 与 `reasoning_effort`，数值来自 `skills/acceptance-testing/config/agent-models.toml`（唯一权威，见 §6）；禁止省略、禁止自行改值。模型不在目录或不支持时，使用该文件的 `[fallback]` 表并记录到 run manifest。
3. 上下文切片：一个子代理只拿它这一个实验/一个 task 所需的内容——所需 Spec 节、相关 ARCHITECTURE 不变量、相关 ADR、相关 raw-report。**禁止把整份 Spec、整份 ARCHITECTURE、整份报告或整个对话历史传给子代理。**
4. 写范围冲突不并行：两个子代理写范围重叠（同一包、同一文件、同一配置键、同一硬件路径）时禁止并行派发。Experiment Agent 只写 `runs/`，可与只读的 Analysis Agent 流水串行；Execution Agent 修改代码时必须按包/文件隔离。
5. 子代理不得自行派生子代理（"You Do Not Dispatch Subagents"）——编排者是唯一派发者。
6. 子代理的完整报告必须落盘到约定文件；回传给编排者的消息只允许摘要（状态、文件路径、关键结果、异常项），避免上下文污染。
7. **禁止阻断子代理**：子代理一旦派发，编排者不得以任何方式中断、强杀、取消或跳过正在执行的子代理——包括但不限于 `interrupt=true`、`close_agent`、`terminate`、强制超时切断。编排者只能用 `wait_agent`（事件订阅，有界等待）等待子代理自然完成；子代理自身遇到的 blocker 必须由它自己在 Execution Report 中声明为 BLOCKED 并停止，编排者不得替它提前中止。反馈/修改轮次通过让子代理自然结束后重新派发新实例实现（传递上一轮的 review 反馈作为新 message），而非中途插入。**唯一例外：用户（人类）明确指示编排者中断某个正在执行的子代理。**

## 6. 模型与权限分配

**模型分配唯一权威：`skills/acceptance-testing/config/agent-models.toml`。** 编排者派发前必须读取该文件，把每个角色的 `model` 与 `reasoning_effort` 显式写入 spawn 参数；修改模型分配只改该文件，然后运行 `python3 skills/acceptance-testing/scripts/acceptance_run.py check-models` 校验（对照模型目录与 `agents/codex-roles/*.md` frontmatter）。

模型名称必须存在于本机模型目录（`~/.codex/opencodex-catalog.json`），不在目录中的模型一律不写配置。跨 Provider 模型（`zai/*`、`deepseek/*`）默认不启用，启用前需人工确认委派链路可靠。

下表是当前默认值速查，**以 config/agent-models.toml 实际内容为准**：

| 角色 | model（默认） | reasoning_effort | 写权限 | 说明 |
| --- | --- | --- | --- | --- |
| Experiment Agent | `gpt-5.6-luna` | medium | 只写 `runs/acceptance/<run-id>/` 与临时目录 | 大量工具调用、中等推理 |
| Analysis Agent | `gpt-5.6-sol` | high | 只读代码；只写 `runs/` 下的报告 | 最强推理 |
| Solution Agent | `gpt-5.6-luna` | high | 只读代码；只写 `runs/` 下的方案 | 架构理解与任务拆分 |
| Execution Agent | `gpt-5.4` | high | 可修改代码但严格限 task 范围 | 中档高性价比实施 |

`agents/codex-roles/*.md` 的 frontmatter `model` 必须与本文件保持一致（`check-models` 会校验），两者是"安装时快捷值"与"运行时唯一权威"的关系。

## 7. Evidence 层与 Probe Points

本项目的验收证据必须围绕真实数据流采集，探针点定义见 `skills/acceptance-testing/references/probe-points.md`：

```text
P0 UDP 输入（loopback scene_payload / captured fixture / 真实 14043）
 ↓
P1 /rokoko/{side}/raw_hand（RawHandFrame）+ receiver 日志
 ↓
P2 /hand_retargeting/{side}/state（RetargetingState）
 ↓
P3 /o10_control/{side}/command（JointState ×10，仅 ready 后发布）
 ↓
P4 /o10/{side}/joint_cmd + /o10_control/{side}/state（O10ControlState）
 ↓
P5 /o10/{side}/joint_states + joint_error_states + read_active_joints srv（software provider 可注入故障）
 ↓
P6 MCAP 录制（ros2 bag record --storage mcap）
```

Analysis Agent 通过 `Expected Pn vs Observed Pn` 寻找 First Divergence。实验 harness 三档：

- A 档（默认，无真机）：`RosGraph` 进程内真实四节点图 + loopback UDP（`src/collection/omni_hand/rokoko_omnihand_system_test/rokoko_omnihand_system_test/graph.py`）。
- B 档：/tmp 独立 colcon 工作区 + `ros2 run` / `ros2 launch` 进程级运行（构建命令与 Python 3.12/mamba 环境要求见 `DOCS/03_工程/03_测试总览与追踪矩阵.md`）。
- C 档：真机 / 生产 Provider（Agilink SDK）——**强制人工 checkpoint**，遵守 `DOCS/02_约束/编程执行/编程执行规则.md` §10 验证阶梯。

## 8. Artifact 管理

沿用仓库既有规范（生成物隔离，`编程执行规则` §12；`/runs/` 已被 `.gitignore` 预留）：

```text
runs/acceptance/<run-id>/            # 不进 Git
├── manifest.md                      # 状态台账：State、循环计数、EXP/TASK 索引、SIMULATION 标记
├── experiments/EXP-nnn/
│   ├── request.md
│   ├── raw-report.md
│   └── artifacts/                   # 原始采集物：topic dump、bag、日志、截图
├── investigation/report.md
├── solution/
│   ├── solution.md
│   └── tasks/TASK-nnn.md
├── execution/TASK-nnn-report.md
└── final-report.md
```

规则：

- run 目录用 `skills/acceptance-testing/scripts/acceptance_run.py init <run-id> --goal "..."` 创建骨架，manifest 为唯一状态权威。
- 每次状态转移后更新 manifest.md 的 State 与索引。
- 桌面演练（未真实运行程序）必须在 manifest.md 顶部标记 `Simulated: true`，所有报告文件头注明 `SIMULATION — 非真实运行证据`，不得伪造运行数据。
- 终局结论影响工程进度时，只在 `DOCS/03_工程/` 写摘要并以仓库相对路径引用 `runs/acceptance/<run-id>/`，原始证据不搬入 DOCS（见 `Agent三层记忆与上下文检索规则`）。

## 9. 编排者输出验证与 Role Violation 处理

不能因为某个 Subagent 返回了一段自然语言就直接继续。以下情况视为 ROLE VIOLATION：

| 违规 | 判据 | 处理 |
| --- | --- | --- |
| Experiment 越权判断 | raw-report 出现因果/意图/方案语句（"原因是/应该是/fail 了/有 bug"等，非程序原始字符串） | 退回重写为纯 Evidence |
| Experiment 越权修改 | 声称或实际修改了 `src/`、测试、DOCS、skills | 立即停止流程，人工处理 |
| Analysis 无证据 | 结论没有 evidence 引用，或 evidence 不足以区分假设就下结论，或直接跳到方案 | 拒收，退回补充实验或重写 |
| Solution 无支撑 | 方案不基于 Investigation Report，或 Micro Task 超过单上下文 | 退回重新拆分 |
| Execution 越权 | 修改超出 task 范围，或宣称问题已解决 / 验收 PASS | 停止流程 |
| 子代理派生子代理 | 任何子代理自行 spawn | 视为违规，编排者接管 |

## 10. 循环与终止

- 必须循环：ANALYZING →（补充实验）→ EXPERIMENTING；EXECUTING → REVALIDATING →（重新）EXPERIMENTING。
- 终止条件（到达任一即停并输出 FINAL_REPORT）：
  1. VERIFIED_PASS（全部验收目标经真实实验复验通过）；
  2. VERIFIED_FAIL（修复循环耗尽仍未复验通过）；
  3. NOT_VERIFIED（存在无实验证据支撑的部分，单独列出，不得并入 PASS）；
  4. EVIDENCE_INSUFFICIENT（预算内无法区分假设）；
  5. BLOCKED（环境/依赖/权限阻断，注明具体缺口）；
  6. OUT_OF_SCOPE（验收目标超出项目当前范围，记录并建议转 issue tracker）；
  7. 循环预算超限（§3 三条硬上限）→ 人工 checkpoint。

## 11. 人工 Checkpoint（必须停下向用户汇报并等待指示）

- 实验需要真机、生产 Provider、外部 SDK（Agilink）、真实 Rokoko 抓包验证；
- 需要破坏性操作或不可逆操作（删除、覆盖原始数据）；
- 循环预算耗尽；
- Spec 预期与现实矛盾，需要修改预期（Agent 不得私自改 Spec）；
- 需要 git 写操作（commit / push / 分支）；
- 需要启用跨 Provider 子代理委派。

## 12. 终态定义

- **VERIFIED_PASS**：全部验收目标经真实实验复验通过，无未解决的 divergence。
- **VERIFIED_FAIL**：存在被证据确认的 divergence，且修复循环耗尽仍未复验通过。
- **NOT_VERIFIED**：没有实验证据支撑的部分——单独列出，绝不与 PASS 混写。
- **EVIDENCE_INSUFFICIENT**：在预算内证据仍不足以确认或排除假设。
- **BLOCKED**：环境、依赖或权限阻断，注明具体缺口。
- **OUT_OF_SCOPE**：目标超出当前项目范围。

## 13. 最终报告（编排者必须产出）

FINAL_REPORT 至少包含：验收目标；状态机经过的完整路径；每个实验的 ID/目标/结论；Investigation 摘要（First Divergence、Root Cause、置信度）；方案与任务清单及各自状态；复验结果；剩余未验证项；人工 checkpoint 记录；终态。

## 14. 启动第一次 Acceptance Run

1. 从 `DOCS/03_工程/00_当前状态.md` 的「外部阻断与未验证」或用户指定目标中确定验收目标；
2. 按 `编程执行规则` §2 加载上下文（AGENTS.md → 编程执行规则 → Spec → ARCHITECTURE → 当前状态 → 本 Skill）；
3. `python skills/acceptance-testing/scripts/acceptance_run.py init <run-id> --goal "<验收目标>"`；
4. 进入 PLANNING → EXPERIMENTING 状态机（§3），按 §5 派发、§9 校验、§10 循环；
5. 产出 final-report.md，按 §8 决定是否更新 `DOCS/03_工程/`。

## 15. What this skill must NOT do

- 代替四个 Subagent 完成它们的核心工作（编排者只做状态管理、派发、上下文打包、输出验证、产物路由、循环控制、人工 checkpoint、最终报告）。
- 在证据不足时得出结论、在未复验时宣称 PASS。
- 修改 Spec、ARCHITECTURE、ADR 或验收目标本身。
- 覆盖 `编程执行规则` 的 Git 安全（§13）与生成物隔离（§12）规则。
- 不经人工 checkpoint 触碰真机、生产 Provider、外部 SDK 或真实抓包。
- 复制 Web/通用 QA 模板——本项目实验必须基于本仓库真实数据流与探针点（§7）。
