# 04 — 三级灯与判活

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 每个方块呈现三级状态灯：绿 = 业务就绪（receiver：raw_hand 流动；重定向：phase==TRACKING 且 command_published；控制：O10ControlState 无 fault；provider：joint_states 流动）；黄 = 进程活着但业务未就绪（如指长收集中）；红 = 进程死亡或数据超时。判活由后端 topic 频率探测完成（阈值按各 topic 预期频率），业务语义从 RetargetingState/O10ControlState 读取，对业务节点零改动、不新增状态 topic。状态经 WebSocket 约 5Hz 推送到前端网格。灯语义用 system_test 真节点图（次接缝）验证：真实状态消息驱动下绿/黄/红转换正确，包括断流转红、COLLECTING_LENGTHS 黄。

**Blocked by:** 02 — 编排核心：期望状态与替身进程。

**Status:** ready-for-agent

- [ ] 后端频率探测按 topic 预期频率设置超时阈值，断流转红
- [ ] 四类节点的绿灯业务语义如 spec 定义，从真实状态消息读取
- [ ] 黄灯覆盖"活着但未就绪"状态（至少含指长收集阶段）
- [ ] 状态经 WebSocket 约 5Hz 推送，前端网格灯实时变化
- [ ] 次接缝测试：system_test 真节点图驱动下灯的绿/黄/红转换全部正确
- [ ] 不改动任何业务节点代码（以现有包 diff 为证）
