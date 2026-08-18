# Launchpad Tickets 索引

M1–M4 的 12 张 tracer-bullet tickets，编号即依赖顺序（阻塞者在前）。每张完成后勾选其验收项并更新状态；下游 ticket 在全部阻塞者完成后进入可开工状态。权威 spec：[08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)。

| # | Ticket | 被阻塞于 | 状态 | 交付 |
| --- | --- | --- | --- | --- |
| 01 | [包骨架与架构治理落地](01-package-skeleton-governance.md) | 无 | ready-for-agent | 控制面可拉起；包入架构治理；两份 ADR |
| 02 | [编排核心：期望状态与替身进程](02-orchestrator-core-standins.md) | 01 | ready-for-agent | API 方块集驱动的进程编排与校验规则 |
| 03 | [前端方块网格页](03-block-grid-frontend.md) | 02 | ready-for-agent | 浏览器配置与运行控制网格 |
| 04 | [三级灯与判活](04-three-level-status-lights.md) | 02 | ready-for-agent | 频率探测 + 业务语义的三级状态 |
| 05 | [真节点接入：数据链路模式与 preflight 迁移](05-real-nodes-datalink-preflight.md) | 02 | ready-for-agent | 真节点替换替身；bash 退役；基线档案 |
| 06 | [合成输入源方块](06-synthetic-input-block.md) | 05 | ready-for-agent | 确定性假帧灌 UDP，零硬件链路 |
| 07 | [录制全家桶与 run 会话](07-recording-run-session.md) | 05 | ready-for-agent | mcap+/rosout+sysmon+metadata+events |
| 08 | [run 历史页](08-run-history-page.md) | 03, 07 | ready-for-agent | run 列表、大小、手动删除、label |
| 09 | [数据流面板 I：关节曲线与 IK 状态](09-stream-panels-joints-ik.md) | 03, 04 | ready-for-agent | 关节目标/反馈曲线、IK 色带与残差 |
| 10 | [数据流面板 II：频率延迟与事件流](10-stream-panels-latency-events.md) | 09 | ready-for-agent | topic 频率、延迟逐跳分解、事件流 |
| 11 | [全链路 sim 模式](11-fullchain-sim-mode.md) | 05 | ready-for-agent | SoftwareO10Provider 全链无真机跑通 |
| 12 | [v1 验收：真机会话与注入故障离线定位](12-acceptance-v1.md) | 01–11 | ready-for-agent | acceptance 取证与门禁全绿 |

当前前沿：**01 可立即开工**；02 完成后 03/04/05 三路并行；05 完成后解锁 06/07/11。

M 对应：M1=01–06，M2=07–08，M3=09–10，M4=11，验收=12。
