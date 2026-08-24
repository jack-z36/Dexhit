# 交接文档：OmniHand O10 驱动模块排查修复（总线映射 + 错误查询接口 + 限速器 1-ulp）

> 生成日期：2026-08-24。面向"继续 O10 遥操作链路维护"的会话。
> 前序会话：`handoff-o10-control-fix.md`（8-18，commu_except 锁存修复，本次大量复用其 SDK 事实）、`HANDOFF.md`（8-17 IK 判别，已完结）。
> 本文件只记录本次会话新增事实，不重复既有文档。

## 1. 一句话总结

用户报告"重定向正常输出但控制不了灵巧手，重点锁定驱动模块"。根因 **3 个叠加问题**，全部已修复并**真机验证通过：左手实时跟随手套，连续运行 8 分钟无故障锁存**（此前 2 分钟内必锁）。

1. **配置把左手指向空 CAN 总线**（主因）：唯一在线的手挂在 `canfd_device_id=1/ch0`，配置却让 `o10.left` 用 `dev0/ch0`（总线上无任何应答）→ 驱动读不到数据 → control 永不使能运动。8.21 提交 `428c956`（消息即"左手改出了一些问题"）把 `o10.right` 从 dev0/ch1 改成 dev1/ch0 时未同步左手。
2. **驱动批量错误查询接口不可靠**：`get_all_error_reports()` 在健康手上偶发返回 0 条（停机直连探测实测 len=0）→ 驱动不发布 → control 错误监控超时 → 锁存 `ERROR_MONITOR_TIMEOUT` → **手在遥操作中突然停住**。
3. **控制层限速器 1-ulp 浮点边界**：手套把关节推到极限时目标正好压在限位上，`基点+差值` 舍入后比限位低 1 ulp（6.9e-18 rad）→ 严格校验判越界 → `SAFETY_INVARIANT` 锁存 → 手冻结（clear_fault 后 1 秒内复锁，确定性）。

## 2. 会话成果（已实测验证）

- **驱动链路恢复**：`/o10/left/joint_states` 2Hz、`/o10/left/joint_error_states` 1.6Hz（修复前两者完全静默）
- **control 干净启动**：`phase 3 (ACTIVE)`、`fault_latched: false`、`motion_enabled: true`、`fault_reason_mask: 0`，**启动即自动使能运动，无需 clear_fault**（此前每次启动必锁）
- **手实时跟随手套**：关节读数实时变化（thumb_mcp -0.457→-0.472 等），`command_published: true`
- **8 分钟稳定性监测**：全程 `fault_latched=false`，provider rclpy 错误 **0 条**（此前每 2s 一条 + 偶发锁存）
- 测试全绿：硬件适配 **24** + contracts **103** + control **68**（含新增回归测试）

## 3. 修改的文件（8 个，全部未提交）

| 文件 | 改动 |
| --- | --- |
| `src/collection/omni_hand/omnihand_o10_hardware_adapter/omnihand_o10_hardware_adapter/backends.py` | `query_errors()` 改用单关节 `get_error_report(j)`（j=1..10）替代批量 `get_all_error_reports()`（文档化 SDK bug） |
| `src/collection/omni_hand/omnihand_o10_hardware_adapter/test/test_agilink_backend.py` | Fake 手改为单关节接口；新增"单关节异常导致整次查询失败"测试 |
| `src/collection/omni_hand/omnihand_o10_hardware_adapter/test/test_provider_contract.py` | 契约文本断言 `get_all_error_reports` → `get_error_report` |
| `src/collection/omni_hand/omnihand_o10_control/omnihand_o10_control/core/slew_limiter.py` | `limit()` 输出 `np.clip(command, lower, upper)` 到限位（吸收 1-ulp 浮点误差，目标超限时命令停在限位上而非锁死） |
| `src/collection/omni_hand/omnihand_o10_control/test/test_slew_limiter.py` | 新增 1-ulp 越界回归测试 |
| `src/collection/omni_hand/rokoko_omnihand_bringup/scripts/start_omnihand_control.sh` | `o10.left.canfd_device_id` 0→1；`o10.right` 1→0（右手未接，指向空总线保持惰性） |
| `src/collection/omni_hand/rokoko_omnihand_bringup/launchpad/default.yaml` | 同上（launchpad 并行启动器，必须同步修否则走 launchpad 仍会坏） |
| `DOCS/03_工程/09_Rokoko到OmniHand_O10全流程启动手册.md` | 设备映射参数同步 |

**无 Python 重建需求**：install 下 egg-link 指向 `build/<pkg>`，而 build 目录是到 src 的符号链接 → 改源码后重启节点即生效。已实测确认。

## 4. 关键事实（本次新增，其他文档没有）

### 硬件现状（8-24 实测）
- **插着两个 CANFD 分析仪**（handoff-o10-control-fix 记录的是 1 个）：Bus 001 Device 045（serial `F0802054386C5430`）与 Device 047（serial `F0802081378C4E31`），产品 ID 均 a8fa:8598
- SDK 枚举 2 个设备：**dev0/ch0 = 空总线（打开成功、发帧无应答）**；**dev1/ch0 = 唯一在线的手**（hand_device_id=1，OMNIHAND-2025，24V，10 DOF）
- 手对 LEFT/RIGHT 手型查询都应答（镜像读数）——软件侧"左右"只影响映射，不能靠它区分物理左右
- 广播发现 API（`get_device_info_from_broadcast`）当前不可用（内部设备枚举失败），别依赖

### 链路与配置
- 数据流：`/o10_control/left/command`（重定向 30Hz）→ control（限速器+安全门）→ `/o10/left/joint_cmd` → provider（SDK）→ CANFD → 手
- `max_joint_rates` 是**按 跨度/0.14s 反推调参**（每关节 span/rate=0.14，凑 0.2s 响应预算：0.06 低通 + 0.14 slew），不是硬件规格；`test_response_budget.py` 从 `launchpad/default.yaml` 读取并断言 ≤0.2s——**改关节限位必须同步重调该关节速率**，否则预算测试挂
- **模型资产校验门**：重定向节点 `omnihand_o10_model/urdf_validator.py` 要求合约 `JOINT_LIMITS` 与外部 fixture URDF 限位**容差一致**（`math.isclose` abs_tol 1e-9）——只改合约限位会导致"model is unavailable"、重定向停摆（本次实测踩坑，已回退）

### 环境陷阱（复用 handoff-o10-control-fix.md §4，摘要）
- conda base python3 是 3.13 会劫持；ROS 代码用 `/usr/bin/python3` 或 `dexhit_collection` env python
- 运行前：`source /opt/ros/jazzy/setup.bash; source install/setup.bash`，且 `PYTHONPATH`/`LD_LIBRARY_PATH` 指向 conda env
- **集成测试干扰**：活图运行时跑 `test_o10_control_node.py` 整文件会有多个失败（真节点同 topic 污染）；**停图后单独跑全部通过**。`test_response_budget.py` 直接用 `/usr/bin/python3 -m pytest` 跑会因缺 PYTHONPATH 报 ModuleNotFoundError——需 source install 后再跑
- `init.sh` 检测到运行节点会拒绝（`--allow-live-graph` 可豁免）；375 测试中 6 个既有失败（架构门 A16 + system_test 时序），与本次改动无关

## 5. 当前系统运行状态

- **bash-6（后台 job）**：完整图运行中（`./start_omnihand_control.sh` 启动），4 节点齐全：rokoko_hand_receiver / hand_retargeting / omnihand_o10_hardware_provider / o10_control_node
- 左手 ACTIVE 跟随手套中；**停止/重启方式：kill bash-6 后重新 `./start_omnihand_control.sh`**
- 若节点死了，用 handoff-o10-control-fix.md §4 的环境变量命令重启（含 PYTHONPATH/LD_LIBRARY_PATH）

## 6. 已知问题与注意事项

- **pinky_abad 校准 -0.19 未应用**：handoff-o10-control-fix 曾实测该手零位 -0.1861 超出合约下限 -0.1850049007113989（会导致 INVALID_FEEDBACK）。本次尝试恢复时发现**合约限位与 fixture URDF 必须一致**（模型校验门）——正确做法是连同版本化外部 fixture（`/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009/urdf/omnihand_left.urdf`）一起更新并重新固定 hash，属单独任务。当前手空闲位 -0.1425 在限位内，暂不阻塞
- **max_joint_rates 是 8.21 改的大速率（8~12 rad/s）**：手跟随快；若要柔和手感可调回 0.1（之前验收用过的安全值）
- **右侧惰性待机**：右手指向空总线，phase 0 永不使能，无日志刷屏（单关节接口返回默认报告不再报错）
- 限速器 `initialize()` 仍是严格限位校验——若手静止在限位 1-ulp 外会 INVALID_FEEDBACK（本次未触发，可作后续 epsilon 容差项）
- 手会应答两种手型查询，物理左右区分只能靠人确认（本次用户确认唯一的手就是左手）

## 7. ⚠️ 未提交变更警告

工作区还有**大量与本次无关的并行改动**（此前 handoff 已警告）。**若要 commit，只提交第 3 节列出的 8 个 o10 文件**，切勿 `git add -A` 全量提交。建议提交信息包含"哪条假设被证实"（按 diagnosing-bugs 惯例）：批量错误接口不可靠 + 1-ulp 限位越界。

## 8. 下一步建议

1. **询问用户是否 git commit** 本次 8 个文件（按第 3 节清单）
2. 若用户要正式验收：戴手套做一轮完整遥操作（握拳/张开/极限位）并采集运行证据（state 无锁存 + 关节跟随）
3. **pinky_abad -0.19 校准**：作为单独任务——同步改合约限位 + fixture URDF + 重调 pinky 速率（0.19/0.14=1.3571 保持 0.2s 预算）+ 跑 urdf_validator 测试
4. 右手接入后的 RIGHT 侧验证；launchpad 走一遍确认 default.yaml 修复生效
5. 可选项：把 `initialize()`/`confirm()` 的限位校验也加 epsilon 容差（同 1-ulp 类问题）

## Suggested Skills

- **`acceptance-testing`** — 用户重视真机运行证据；对本次修复做一轮真机验收（戴手套全程遥操作 + 极限位场景 + 稳定性采样）最契合
- **`code-review`** — 提交前对本次 8 个文件做 Standards + Spec 双轴审查
- **`to-tickets`** — 若把 pinky 校准（合约+fixture+速率联动）、右手接入、epsilon 容差拆成 tickets
- **`research`** — 若需核实 fixture 更新流程（URDF 限位来源、hash 固定机制）或 SDK 单关节接口细节，可让子代理到 `/home/hit/dexhit相关开源项目/agillink_omnihand_sdk` 深挖并落档
- **`diagnosing-bugs`** — 若用户再报硬件/链路问题，本会话的直连 SDK 探测手法（`/tmp/sdk_probe_all_combos.py`、`/tmp/err_ts.txt` 分析）可复用
