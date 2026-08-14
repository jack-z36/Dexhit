# Dexhit 全局路由入口

本文件是仓库唯一全局路由入口，只说明开始任务时要读取哪些权威入口，不承载项目知识、规则正文、工程状态或执行记录。

所有任务先遵循 [Agent 三层记忆与上下文检索规则](DOCS/02_约束/文档体系/Agent三层记忆与上下文检索规则.md)，再按下表加载任务相关入口。

## 任务路由

| 任务类型 | 开始前读取 |
| --- | --- |
| 理解项目、规划或讨论术语 | [用户概念体系](DOCS/02_约束/用户概念体系/用户概念与术语规则.md)，再按需读取 [项目知识](DOCS/01_知识/INDEX.md) |
| 编码、测试、Debug、Git 或 Skill | [编程执行规则](DOCS/02_约束/编程执行/编程执行规则.md)，再读取相关知识、工程状态和 [Skill 索引](skills/INDEX.md) |
| 创建、迁移、分类或维护文档 | [文档维护规则](DOCS/02_约束/文档体系/文档维护规则.md)，再读取相关目录的 `INDEX.md` |
| 查询具体任务进度 | [当前状态](DOCS/03_工程/00_当前状态.md) |

任务跨越多个类型时，读取所有对应入口。默认不读取 [archive](DOCS/98_archive/INDEX.md) 和 [learning](DOCS/99_learning/INDEX.md)，除非用户明确要求历史追溯或学习资料。

## Agent skills

### Issue tracker

Issues 和 specs 以 GitHub issues 形式存在（仓库 jack-z36/Dexhit），用 `gh` CLI 操作。见 [DOCS/02_约束/编程执行/issue-tracker.md](DOCS/02_约束/编程执行/issue-tracker.md)。

### Triage labels

使用五个规范 triage 角色标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。见 [DOCS/02_约束/编程执行/triage-labels.md](DOCS/02_约束/编程执行/triage-labels.md)。

### Domain docs

单上下文布局：仓库根 `CONTEXT.md` + `DOCS/01_知识/ADR/`。见 [DOCS/02_约束/编程执行/domain-docs.md](DOCS/02_约束/编程执行/domain-docs.md)。
