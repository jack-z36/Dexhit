# 09 — 数据流面板 I：关节曲线与 IK 状态

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 点击节点方块打开数据流页，每侧呈现两组为人类优化的实时面板：其一，10 个主动关节的目标（command）与反馈（joint_states）时间序列曲线，可叠加限幅后 joint_cmd；其二，重定向 phase 时间线、五指 IK 状态色带（ik_state 逐指着色）与归一化残差曲线。面板数据来自真实 topic 的下采样流（约 10Hz 更新），数值语义经次接缝（system_test 真节点图）验证正确，不是装饰性图表。

**Blocked by:** 03 — 前端方块网格页；04 — 三级灯与判活。

**Status:** ready-for-agent

- [ ] 每侧 10 关节目标与反馈曲线实时呈现，joint_cmd 可选叠加
- [ ] phase 时间线随 RetargetingState 变化着色
- [ ] 五指 IK 状态色带与归一化残差曲线逐指呈现
- [ ] 面板约 10Hz 更新且下采样不引入可感知卡顿
- [ ] 次接缝测试：面板数值与真实 topic 数据一致（含 IK 失败注入时色带变化）
