# 12 — v1 验收：真机会话与注入故障离线定位

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 按 acceptance-testing 流程对 v1 做基于真实运行证据的验收。硬标准一：一次真机遥操作会话，全程仅通过网页完成启动 → 监控（三级灯与数据流面板）→ 开录 → 停止，终端只用于 arm 授权。硬标准二：会话中人为注入至少两类故障（如 kill 掉 provider、断开 UDP 流），事后仅凭 run 目录离线分析（mcap + /rosout + metadata + events + sysmon + 节点日志，不看现场终端输出），正确定位每个故障的责任环节，且结论可由第三方复现。未通过则强制回到对应 ticket 修复并重新进入验收循环。

**Blocked by:** 01–11 全部完成。

**Status:** ready-for-agent

- [ ] 真机会话全程仅网页操作完成（截图/录屏 + events 时间线为证），终端仅 arm
- [ ] 开录的 run 目录包含全 topic mcap（含 O10ControlState、joint_cmd、joint_states、joint_error_states）与 /rosout
- [ ] 注入故障至少两类，仅凭 run 目录离线定位责任环节且结论正确
- [ ] 离线分析结论可复现（另一会话按报告重放得出同样定位）
- [ ] 架构门禁全绿（含 sim/真机引用边界门禁）
- [ ] 验收报告落 DOCS/03_工程，含证据链与残余问题清单
