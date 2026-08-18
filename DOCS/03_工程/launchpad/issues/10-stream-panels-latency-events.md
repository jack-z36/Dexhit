# 10 — 数据流面板 II：频率延迟与事件流

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 数据流页补齐另两组面板：其一，各 topic 的实时频率仪表（raw_hand、retargeting state、command、joint_cmd、joint_states 等）与端到端延迟的逐跳分解图——沿既有时间戳链（source_timestamp → 接收 stamp → input_stamp → solve 完成 → command → joint_cmd → joint_states）计算每跳延迟并滚动呈现，使延迟劣化能定位到具体链路段；其二，fault 状态面板与实时事件流（与 events.jsonl 同源：网页打标、方块启停、节点告警），异常与操作呈现在同一条时间线上。

**Blocked by:** 09 — 数据流面板 I：关节曲线与 IK 状态。

**Status:** ready-for-agent

- [ ] 各 topic 实时频率呈现且与实际发布频率一致（次接缝验证）
- [ ] 端到端延迟逐跳分解正确计算自各消息时间戳，无跳缺失真
- [ ] fault 状态面板与 O10ControlState 的 fault 位一致
- [ ] 事件流实时滚动，与 events 记录同源同序
- [ ] 面板约 10Hz 更新
