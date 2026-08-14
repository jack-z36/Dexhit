# Skill 索引

`skills/` 是仓库内 Skill 的唯一权威实体目录。只有任务触发对应 Skill 时，才读取该 Skill 的完整 `SKILL.md`；新增或移动 Skill 必须同步本索引。

| Skill | 用途 | 触发条件 | 入口 |
| --- | --- | --- | --- |
| `code-review` | 对固定基点以来的变更做规范与规格双轴审查 | 用户要求 review、审查分支或 PR | [SKILL.md](code-review/SKILL.md) |
| `codebase-design` | 用 deep module 词汇设计或改进模块接口 | 讨论模块接口、可测试性或架构深化 | [SKILL.md](codebase-design/SKILL.md) |
| `architecture-design` | 把已有 Spec 映射为 Codebase Architecture（层级/依赖规则/包边界/端口适配器/不变量/架构测试），产出 `DOCS/01_知识/ARCHITECTURE.md` | 用户有 spec 要设计代码库架构、层级或依赖设计 | [SKILL.md](architecture-design/SKILL.md) |
| `architecture-review` | 审查 ARCHITECTURE.md 的完整性、内部一致性和可机械执行性（结构审查，非行为） | 用户要审查架构是否完整/可执行，或 architecture-design 之后 | [SKILL.md](architecture-review/SKILL.md) |
| `diagnosing-bugs` | 对困难 bug 和性能回归建立诊断循环 | 用户要求 diagnose/debug 或报告失败、变慢 | [SKILL.md](diagnosing-bugs/SKILL.md) |
| `dispatch-tickets` | 用 sub-agent 并行派发执行一组实现 ticket（依赖波次 + 冲突隔离 + 三轮迭代） | 用户有一组 ticket/实施计划要在一个会话内高效并行执行 | [SKILL.md](dispatch-tickets/SKILL.md) |
| `domain-modeling` | 建立和收紧项目领域模型 | 用户要明确术语、上下文或架构决策 | [SKILL.md](domain-modeling/SKILL.md) |
| `grill-me` | 进入持续追问的方案澄清会话 | 用户明确要求 grill | [SKILL.md](grill-me/SKILL.md) |
| `grill-with-docs` | 追问方案并同步形成 ADR/术语领域文档 | 用户要求 grill 且要产出 ADR/术语文档 | [SKILL.md](grill-with-docs/SKILL.md) |
| `grilling` | 以设计树方式压力测试计划或想法 | 用户要求压力测试计划、决定或想法 | [SKILL.md](grilling/SKILL.md) |
| `handoff` | 生成供下一 Agent 接续的交接文档 | 用户要求 handoff 或会话交接 | [SKILL.md](handoff/SKILL.md) |
| `implement` | 按规格或 ticket 实现工作 | 用户要求按 spec/ticket 实现 | [SKILL.md](implement/SKILL.md) |
| `improve-codebase-architecture` | 扫描并呈现架构深化机会 | 用户要求架构改进扫描或报告 | [SKILL.md](improve-codebase-architecture/SKILL.md) |
| `loop-me` | 为重复工作设计 workflow 规格 | 用户要求设计 workflow loop | [SKILL.md](loop-me/SKILL.md) |
| `research` | 基于一手来源研究并写入 Markdown | 用户要求查资料、API 事实或研究报告 | [SKILL.md](research/SKILL.md) |
| `setup-matt-pocock-skills` | 为仓库初始化 issue tracker、triage 标签和领域文档布局 | 用户要求初始化/配置 skills，或其他 skill 引用缺失的 `DOCS/02_约束/编程执行/issue-tracker.md` | [SKILL.md](setup-matt-pocock-skills/SKILL.md) |
| `tdd` | 以 red-green-refactor 驱动测试 | 用户要求 TDD、测试先行或集成测试 | [SKILL.md](tdd/SKILL.md) |
| `teach` | 在工作区持续教授概念或技能 | 用户要求学习或教学会话 | [SKILL.md](teach/SKILL.md) |
| `to-spec` | 把对话整理为规格并发布到 issue tracker | 用户要求生成并发布 spec | [SKILL.md](to-spec/SKILL.md) |
| `to-tickets` | 把计划拆成带阻塞关系的 tickets | 用户要求拆 tickets 或任务切片 | [SKILL.md](to-tickets/SKILL.md) |
| `triage` | 把 issues/PR 推过 triage 状态机并写出 agent-ready brief | 用户要求 triage、加标签或整理 inbox | [SKILL.md](triage/SKILL.md) |
| `wayfinder` | 把超大块工作规划为 issue tracker 上的决策 ticket 地图 | 用户要为一个超大、模糊的目标规划路径 | [SKILL.md](wayfinder/SKILL.md) |
