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

## 修复记录（2026-08-19）：真机四节点启动

**症状**：点"真机 + 启动"后 receiver 拉起但永远显示"启动中"，其余三节点起来即退（retargeting 码 2、provider/control 码 1）。

**根因链（run 目录 logs/ 原始日志定位）**：
1. `ros2 run` 命令直接追加 `-p key:=value` 缺 `--ros-args`，rcl 把参数解析成 remap 全部丢弃 → provider 报 `missing o10.left.transport`、control 报 `missing left.max_joint_rates`；
2. retargeting wrapper 环境守卫缺 `DEXHIT_COLLECTION_PREFIX`/`OMNIHAND_O10_MODEL_FIXTURE` → 退出码 2；
3. 编排器没有任何 `starting→running` 转换（进程退出才变 crashed）→ receiver 永远"启动中"；
4. `retargeting_params` 的 `${VAR:-default}` 被 `os.path.expandvars` 原样透传 → `--params-file` 收到字面量路径崩溃；
5. 档案缺 `recovery_confirmation_timeout_sec`（8-17 验证命令行里显式传过 0.5）；
6. `duplicate_nodes` 预检在重启时会被 DDS 未清退的死节点误拒（提示语已澄清 + 有界 settle 等待）；
7. 结构性缺陷：PDEATHSIG 只挂在 `ros2 run` 直接子进程，编排器被杀时真节点孤儿化残留在 ROS 图（已实测复现并修复）。

**修复**：① 命令构造补 `--ros-args` 作用域；② 真节点 env 叠加档案 `env:` 段（wrapper 守卫两变量，兜底 `sys.prefix`）；③ `snapshot()` 增加就绪宽限期 `starting→running`（`ready_grace` 默认 2s）；④ 新增 `_resolve_profile_path` 支持 `${VAR:-default}`；⑤ 档案补全双侧全部已验证控制参数 + `recovery_confirmation_timeout_sec` + env 段；⑥ 新增 `pdeath_guard` 模块：作为直接子进程接管父死亡时对整组的 TERM→KILL 清理（含 5s 升级、孤儿父检测），真节点与 recorder 均接入；⑦ `start_all` 对仅 `duplicate_nodes` 失败做有界 settle 重试。

**验证证据**：pytest 79 项全过（新增 --ros-args 作用域、路径展开、starting→running、guard 孙进程清理、settle 成功/失败两路径、recorder 退出码语义）；浏览器黑盒：真机模板启动后四节点全部"运行中"，`ros2 node list` 见 4 节点，全停后无任何残留进程；编排器被 SIGKILL 后 guard 自动清掉全部孙进程（实测复现过修复前的孤儿并确认修复后不再出现）。

**遗留（真机联调层，非编排问题）**：retargeting 报 O10 模型资产 `L_pinky_abad_joint` 限位与契约不一致（declared [-0.185, 0.0] vs contract [-0.19, 0.0]）；provider 报 HCAN 发送失败。两者均已在 run 目录 logs/ 留证。
