# 01 — 包骨架与架构治理落地

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 工程师在本机运行一条命令即可拉起 Launchpad 控制面：FastAPI 服务监听 127.0.0.1:8710，浏览器打开显示中文占位首页；同时新包 `rokoko_omnihand_launchpad`（位于 `src/collection` 下与 `omni_hand` 平级）作为受架构治理的一等成员落地——进入架构文档的包职责表、依赖 DAG 与 Port/Adapter 表，两份 ADR（真机模式编排配置禁引 system_test 的边界修订；launchpad 作为设备编排层的定位与依赖方向）成文，架构门禁测试纳入新包。单实例锁防止第二个控制面启动。此阶段不含任何业务节点启动能力。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] 一条命令拉起控制面，浏览器 127.0.0.1:8710 显示占位首页；控制面退出后无残留进程
- [ ] 第二个实例被单实例锁拒绝并有明确提示
- [ ] 包位于 src/collection 下与 omni_hand 平级，出现在 ARCHITECTURE.md 包表、依赖 DAG 与 Port 表中
- [ ] 两份 ADR 成文并入 ADR 索引（A08 边界修订、launchpad 定位与依赖方向）
- [ ] 架构门禁测试纳入新包且全绿
- [ ] 前端工程脚手架（Vite + Vue3 + ECharts）可构建，构建产物不进 git
