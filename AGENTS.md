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

## Rokoko → OmniHand O10 专用开工自检

凡是涉及 Rokoko 手套、手部重定向、OmniHand O10、其 ROS 链路、Launchpad、回放、测试或真机适配的任务，在读取本文件和对应任务入口后，**正式执行任何任务前必须先运行**：

```bash
bash src/collection/omni_hand/init.sh
```

该脚本只负责确认软件基线（worktree、ROS Jazzy、数值环境、模型 fixture、构建和测试），默认检测并拒绝遗留的相关 ROS 节点；它不会启动节点、发布命令、清故障或驱动实体手。依赖安装需显式使用 `--install`，真实硬件启动仍必须遵循 `DOCS/03_工程/09_Rokoko到OmniHand_O10全流程启动手册.md` 的人工安全检查。

对于真正启动遥操作程序，仓库根目录的 `./start_omnihand_control.sh` 是唯一的第一优先级 Agent/操作者入口。执行顺序必须是：先运行上面的 `init.sh`，通过后再运行：

```bash
./start_omnihand_control.sh
```

不要直接调用 `src/collection/omni_hand/rokoko_omnihand_bringup/scripts/start_omnihand_control.sh`；该路径仅作为兼容转发后的实现路径保留。根入口会自动锚定 worktree，并把参数原样转交给实现脚本。

任务跨越多个类型时，读取所有对应入口。默认不读取 [archive](DOCS/98_archive/INDEX.md) 和 [learning](DOCS/99_learning/INDEX.md)，除非用户明确要求历史追溯或学习资料。

## Agent skills

### Issue tracker

Issues 和 specs 以 GitHub issues 形式存在（仓库 jack-z36/Dexhit），用 `gh` CLI 操作。见 [DOCS/02_约束/编程执行/issue-tracker.md](DOCS/02_约束/编程执行/issue-tracker.md)。

### Triage labels

使用五个规范 triage 角色标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。见 [DOCS/02_约束/编程执行/triage-labels.md](DOCS/02_约束/编程执行/triage-labels.md)。

### Domain docs

单上下文布局：仓库根 `CONTEXT.md` + `DOCS/01_知识/ADR/`。见 [DOCS/02_约束/编程执行/domain-docs.md](DOCS/02_约束/编程执行/domain-docs.md)。
