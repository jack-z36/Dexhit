# Dexhit

Dexhit 是一条从机器人数据采集到模型部署的最小工程骨架。当前版本先固定目录、术语、数据主链和文档入口，不预先承诺具体消息 schema、硬件包或第三方依赖。

主数据链：

```text
collection → raw MCAP → processing → LeRobotDataset v3 → training → ACT bundle → deployment
```

入口：

- [项目知识](DOCS/01_知识/INDEX.md)
- [项目约束](DOCS/02_约束/INDEX.md)
- [当前工程状态](DOCS/03_工程/INDEX.md)
- [源码阶段](src/README.md)
- [Skill 索引](skills/INDEX.md)

开始任何任务前，先阅读 [AGENTS.md](AGENTS.md)；它只负责把任务路由到必要的权威文档。
