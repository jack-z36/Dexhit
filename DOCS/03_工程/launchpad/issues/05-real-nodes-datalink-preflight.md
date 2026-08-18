# 05 — 真节点接入：数据链路模式与 preflight 迁移

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 方块从替身换成真节点：点亮数据链路组合后，真 rokoko_hand_receiver 与真 hand_retargeting（以源码 wrapper 方式启动，规避本机无 colcon 的环境约束）作为编排器子进程运行，raw_hand → RetargetingState → command 链路真实出数，三级灯对真重定向状态生效。bash 一键脚本的全部 preflight 检查逐条迁入编排器并条件化（ros2 可用性、数值环境可 import 关键库、参数档案存在、节点查重、hcan 亮才检测 USB-CANFD 设备），bash 脚本退役删除。真机 4 进程组合（receiver、retargeting wrapper、hcan provider、control 及其全部参数）在编排器中定义，基线参数档案（取自已验证真机会话的参数值）进入 bringup 包 launchpad 目录并在网页档案下拉可选；无硬件环境下选真机组合被 preflight 明确拒绝并给出原因。

**Blocked by:** 02 — 编排核心：期望状态与替身进程。

**Status:** ready-for-agent

- [ ] 数据链路组合点亮后真 receiver + 真 retargeting 运行，公开 topic 真实出数（可用 ros2 topic 验证）
- [ ] 重定向以源码 wrapper 启动，参数来自所选档案
- [ ] preflight 检查项逐条迁移且条件化；无硬件环境选真机组合被拒绝且原因明确
- [ ] 真机 4 进程组合与参数在编排器中定义完整
- [ ] 基线参数档案进入 bringup 包 launchpad 目录（git 内），网页可选
- [ ] bash 一键脚本删除，交接说明指向网页流程
- [ ] 三级灯对真 retargeting 状态（COLLECTING_LENGTHS → TRACKING）正确转换
