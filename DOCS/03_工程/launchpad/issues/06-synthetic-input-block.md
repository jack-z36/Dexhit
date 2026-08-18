# 06 — 合成输入源方块

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 点亮合成输入源方块后，编排器启动假帧发送进程：复用 system_test 的确定性场景生成器，向 receiver 监听的 UDP 端口灌入 JSON v3 假帧；配合数据链路模式实现零硬件全链演示——receiver 真实收到并发布 raw_hand，重定向进入 TRACKING 绿灯，command 持续输出。该组合同时成为 web 工具与重定向行为的无硬件回归入口。混流黄提示在点亮该方块时呈现（同一 UDP 端口两路数据风险）。依据 01 落地的 ADR，mock 模式编排配置允许引用 system_test 包。

**Blocked by:** 05 — 真节点接入：数据链路模式与 preflight 迁移。

**Status:** ready-for-agent

- [ ] 点亮合成输入源方块启动假帧进程，真 receiver 收到并发布 raw_hand
- [ ] 数据链路模式 + 合成输入组合下重定向达到 TRACKING 绿灯且 command 持续输出
- [ ] 帧内容确定性可复现（同配置两次运行的场景序列一致）
- [ ] 混流黄提示在该方块点亮时呈现
- [ ] 该组合可作为无硬件回归入口被主/次接缝测试复用
