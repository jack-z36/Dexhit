# 报告模板（acceptance-testing）

所有报告都是 Markdown 文件，落盘到 `runs/acceptance/<run-id>/` 对应位置。模板中的 `{{...}}` 是占位符。桌面演练（未真实运行程序）必须在文件顶部额外标注：

```text
> SIMULATION — 非真实运行证据。本文件不证明程序行为，仅用于演练工作流。
```

## 1. Experiment Request — `experiments/EXP-nnn/request.md`

```markdown
# Experiment Request EXP-{{nnn}}

- Run ID: {{run-id}}
- Requested by: {{编排者 / Analysis Agent（补充实验时注明由哪个假设驱动）}}
- Date: {{ISO datetime}}

## Objective
{{本次实验要回答的一个明确问题；必须可被观测结果回答}}

## Environment
{{harness 档位（A/B/C）、节点与参数、依赖环境、git revision}}

## Preconditions
{{实验开始前必须成立的条件；不成立时实验不得开始}}

## Stimulus
{{P0 输入：合成场景 / captured fixture / 真实抓包；具体内容与速率}}

## Execution Procedure
1. {{步骤 1：启动什么、用什么命令}}
2. {{步骤 2：施加什么输入、持续多久}}
3. ...

## Signals To Observe
{{观察目标探针点 P?、具体字段/枚举/阈值}}

## Artifacts To Collect
{{topic echo 文件、bag、日志、进程状态、退出码；写入 artifacts/ 的文件名}}

## Duration / Stop Condition
{{实验时长或停止条件；超时视为数据，不算失败}}

## Required Repetitions
{{重复次数；随机/时序类实验至少 3 次}}
```

## 2. Raw Experiment Report — `experiments/EXP-nnn/raw-report.md`

```markdown
# Raw Experiment Report EXP-{{nnn}}

## Experiment ID
{{EXP-nnn；对应 request.md}}

## Environment Snapshot
{{git revision（git rev-parse HEAD）、运行命令原文、环境变量、参数覆盖、时间}}

## Code Revision
{{当前 worktree 与 commit；与验收目标相关的未提交改动也列出}}

## Configuration
{{节点参数与 launch 配置；缺失即写缺失}}

## Commands Executed
{{逐条列出实际执行过的命令}}

## Input / Stimulus
{{实际施加的输入；与 request.md 的偏差必须记录}}

## Raw Observations
{{纯事实：时间点、数值、枚举、状态转移}}

## Topic / Service Data
{{P1–P5 原始数据：字段值、缺失 topic、未收到数据}}

## Logs
{{节点日志关键行；原始日志存 artifacts/}}

## Timing Data
{{关键时间戳与间隔；与探针对齐信息}}

## Process Status / Exit Codes
{{进程存活状态、退出码}}

## Artifacts Produced
{{artifacts/ 下文件清单}}

## Missing Data
{{应该采集但未采集到的内容；明确"未采集"，不解释为"不存在"}}

## Execution Errors
{{执行期错误：命令失败、超时、环境报错；原文记录}}
```

## 3. Investigation Report — `investigation/report.md`

```markdown
# Investigation Report — Run {{run-id}}

## 1. Ideal State
{{Spec 预期：每个相关探针点的期望行为；引用 Spec 章节}}

## 2. Observed State
{{实际发生了什么；引用具体 raw-report}}

## 3. Divergence
{{First Divergence 位置：第一次偏离发生在哪个探针点（P0–P6）、什么时刻/什么数值}}

## 4. Cause Analysis
- 直接原因：{{...}}
- 深层原因：{{...}}
- Root Cause：{{CONFIRMED ROOT CAUSE 或 HYPOTHESIS}}

## 5. Evidence
{{每条结论对应哪些 Experiment Evidence：EXP-nnn/raw-report.md 的具体行/数值/文件}}

## 6. Rejected Hypotheses
{{哪些猜想已被实验排除、被哪个实验排除}}

## 7. Remaining Uncertainty
{{还有哪些内容没有证实；需要什么实验才能证实}}

## 8. Confidence
{{对 Root Cause 的置信程度：高/中/低 + 理由}}

> 全文每句标注：FACT / INFERENCE / HYPOTHESIS / CONFIRMED ROOT CAUSE / UNKNOWN
```

## 4. Solution Proposal — `solution/solution.md`

```markdown
# Solution Proposal — Run {{run-id}}

## Confirmed Problem
## Confirmed Root Cause
## Target State
## Proposed Change
## Affected Modules
## Architecture Impact
## Interface Impact
## State Impact
## Regression Risk
## Safety Risk
## Verification Strategy
{{如何验证修复后现实达到 Target State；对应探针点}}

## Micro Tasks
{{TASK-nnn 列表 + 依赖关系}}
```

## 5. Micro Task — `solution/tasks/TASK-nnn.md`

```markdown
# TASK-{{nnn}} — {{一句话目标}}

## Goal
## Context
## Allowed Scope
## Forbidden Scope
## Required Changes
## Expected Behavior
## Acceptance Criteria
- [ ] {{可勾选验收标准 1}}
- [ ] {{可勾选验收标准 2}}

## Verification Command
{{仓库内真实存在的命令；含环境要求}}

## Dependencies
{{依赖的 TASK / EXP / 人工前置}}
```

## 6. Execution Report — `execution/TASK-nnn-report.md`

```markdown
# Execution Report — TASK-{{nnn}}

## Task ID
## Files Changed
## Behavior Changed
## Commands Executed
## Developer Verification
{{实际运行的命令 + 输出摘要；失败必须原文记录}}
## Unexpected Findings
## Blocked Items
{{BLOCKED 时说明缺什么；不自行重新设计}}
## Not Verified
{{未验证项与原因}}
```

## 7. Final Report — `final-report.md`

```markdown
# Final Acceptance Report — Run {{run-id}}

## Acceptance Goal
## State Machine Path
{{PLANNING → ... → 终态；含循环次数}}

## Experiments
| EXP | 目标 | 结论 | 证据 |
| --- | --- | --- | --- |

## Investigation Summary
{{First Divergence、Root Cause、Confidence}}

## Solution & Tasks
{{方案摘要；task 状态表（done / blocked / failed / not-verified）}}

## Revalidation Result
{{修复后复验实验与结论}}

## Final State
{{VERIFIED_PASS / VERIFIED_FAIL / NOT_VERIFIED / EVIDENCE_INSUFFICIENT / BLOCKED / OUT_OF_SCOPE}}

## Remaining Unverified Items
## Human Checkpoints
## Limitations
```
