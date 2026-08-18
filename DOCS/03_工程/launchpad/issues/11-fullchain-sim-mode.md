# 11 — 全链路 sim 模式

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 全链路 sim 模板可点亮 [receiver, retargeting, control, sim provider] 组合：SoftwareO10Provider（复用 system_test 实现，依据 ADR 的 mock 边界）替代硬件 provider 作为编排器子进程运行，无真机跑通 receiver → 重定向 → 控制 → 软件 provider 的完整链路；control 对软件 provider 的反馈与错误 topic 正常工作，全链绿灯可达成。真机模式编排配置禁引 system_test 成为可执行的架构门禁：真机组合引用测试包即测试失败。

**Blocked by:** 05 — 真节点接入：数据链路模式与 preflight 迁移。

**Status:** ready-for-agent

- [ ] 全链路 sim 模板点亮后四进程运行，控制节点消费软件 provider 反馈，全链绿灯可达成
- [ ] command → joint_cmd → joint_states 闭环在无真机环境真实流转
- [ ] hcan 与 sim provider 互斥在真机/sim 组合切换时持续生效
- [ ] 架构门禁测试：真机模式编排配置引用 system_test 即失败
- [ ] 无真机环境下完整演示一次全链路 sim 会话（含开录）
