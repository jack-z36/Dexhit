# Launchpad 网页一键启动遥操作系统 Spec

状态：ready-for-agent（按用户要求不发布 GitHub issue，以本文档为权威）

## Problem Statement

真机遥操作会话目前的启动方式是多个终端手工拉起进程，或依赖一个未纳入 git 的一键 bash 脚本：脚本参数硬编码，只支持单一启动组合；启动配置分散在环境变量、命令行参数和仓库外的参数文件里。想换一种组合（只跑单侧、不接真机、不用手套）必须改脚本或手工重排终端。

会话运行中，节点是否健康只能靠 `ros2 node list` 和终端滚动日志判断；重定向是否真的在出命令、控制是否有故障、硬件反馈是否在流动，都分散在不同终端里，没有统一的可视化状态。

事后分析时，录制需要手工另起 rosbag 进程，且现有录制只覆盖 6 个 topic，控制状态、最终命令、硬件反馈和节点告警日志都没有留存；一次会话没有结构化的边界（起止、参数快照、事件标记），定位问题时证据链不完整。

操作者需要的是：在网页上点一下就能启动整个遥操作程序，灵活选择启动组合，实时看到每个节点的健康状态并查看为人类优化过的数据流，并把一次会话的关键原始数据结构化地录下来，供离线定位链路问题。

## Solution

建立两级启动结构：一键脚本只负责拉起网页控制面（编排器 + 前端），零业务节点副作用；所有节点、录制、停止都由网页操作触发。

控制面核心是**期望状态方块网格**：七个方块（四个业务节点、sim provider、合成输入源、录制器），方块亮代表该进程应该在运行。启动前，网格是配置——模式模板（真机 / 数据链路 / 全链路 sim）一键预点亮一组方块，之后可自由增删，最终运行完全由点亮的方块决定；启动后，网格是运行控制——点击方块即启动或停止对应进程，网格始终显示期望状态与实际状态的差异（期望亮但进程死了为红闪）。侧别（双侧 / 仅左 / 仅右）为独立选择器，业务调参锁定在预设档案中，网页只暴露少数关键参数。

状态监控采用三级灯（绿 = 业务就绪、黄 = 活着但未就绪、红 = 进程死亡或数据超时），判活由后端 topic 频率探测完成，对业务节点零改动。数据流页提供每侧四个面板：关节目标与反馈曲线、重定向 phase 时间线与五指 IK 状态、topic 频率与端到端延迟分解、故障与事件流。

每次启动自动形成 run 会话目录：节点日志、参数与方块清单快照、事件标记总是留存；勾选开录后追加覆盖全部公开 topic 与 /rosout 的 MCAP 录制和系统资源采样。事后仅凭一个 run 目录即可离线分解每跳延迟、定位数据中断的责任环节。

安全底线：网页不暴露 arm/disarm/clear_fault，授权仍由操作者在终端显式完成；编排器以任何方式死亡（含 kill -9）时所有业务节点跟随退出，绝不留真机悬空运行；节点崩溃只告警，不自动拉起。

## User Stories

1. As an 操作者, I want 在工作站本机浏览器打开一个控制页即可管理整个遥操作程序, so that 我不再维护多终端手工启动流程。
2. As an 操作者, I want 一键脚本只拉起网页控制面而不启动任何业务节点, so that 脚本本身永远零副作用。
3. As an 操作者, I want 点一个模式模板自动点亮一组节点方块, so that 常用启动组合一键可达。
4. As an 操作者, I want 逐个点亮或熄灭方块自由组合本次要启动的进程, so that 最终运行完全由我点亮的方块决定。
5. As an 操作者, I want 启动后方块网格变成运行控制（点亮即启动、熄灭即停止）, so that 配置和控制是同一套心智模型。
6. As an 操作者, I want 网格显示期望状态与实际状态的差异（期望亮但进程死为红闪）, so that 进程崩溃一眼可见。
7. As an 操作者, I want 选择双侧、仅左或仅右, so that 单手会话少一半链路且录制更干净。
8. As an 操作者, I want 通过预设档案选择参数而不是在网页编辑 60+ 调参, so that 验证过的参数不会被误改。
9. As an 操作者, I want 网页只暴露少数关键参数（UDP 端口、actor 序号、CAN 通道）, so that 常用变化不用动档案文件。
10. As an 操作者, I want 给本次运行填写一个 label, so that run 历史可辨识。
11. As an 操作者, I want 真机 provider 与 sim provider 同时点亮被硬阻止, so that 不会有两种硬件后端抢占同一反馈 topic。
12. As an 操作者, I want 合成输入加真机 provider 的组合出现红色横幅与二次确认, so that 不戴手套驱动真手永远是显式决定。
13. As an 操作者, I want 点亮合成输入源时收到 UDP 混流提示, so that 真手套数据流被假帧污染时我有预期。
14. As an 操作者, I want 孤儿组合（如 control 无 provider）不被阻止但给出黄提示, so that 诊断姿势不被工具妨碍。
15. As an 操作者, I want preflight 随方块集条件化（hcan 亮才查 USB-CANFD 设备）, so that 不相关的检查不会挡住启动。
16. As an 操作者, I want 一键全启动按依赖顺序拉起节点, so that 我不用手动排序。
17. As an 操作者, I want 一键全停按反序停掉所有进程, so that 一键等价于原来脚本的 Ctrl-C 全停。
18. As an 操作者, I want 整体重启, so that 改完档案后能快速重开会话。
19. As an 操作者, I want 运行中启动或 停止单个节点并看到下游影响提示, so that 故障传播是知情决定。
20. As an 操作者, I want 节点崩溃被检测并亮红灯告警但不自动拉起, so that 硬件控制链路不会中途自动复活。
21. As an 操作者, I want 每个节点有三级灯（绿=业务就绪、黄=活着但未就绪、红=死亡或超时）, so that "稳定输出数据了"一眼可判。
22. As an 操作者, I want 重定向节点绿灯的语义是 phase 为 TRACKING 且 command_published, so that 绿灯就是"真的在出命令"。
23. As an 操作者, I want 判活机制不改动任何业务节点代码, so that web 工具不给遥操作链引入新变量。
24. As an 操作者, I want 点击节点看到为人类优化的数据流面板而不是终端日志, so that 读数是给人看的。
25. As an 操作者, I want 每侧看到 10 个主动关节的目标与反馈曲线, so that 重定向与跟踪质量直观可见。
26. As an 操作者, I want 看到重定向 phase 时间线、五指 IK 状态色带与残差曲线, so that IK 失败能定位到具体手指。
27. As an 操作者, I want 看到各 topic 实时频率与端到端延迟逐跳分解, so that 延迟劣化能定位到具体链路段。
28. As an 操作者, I want 看到 fault 状态与实时事件流, so that 异常与我的操作在同一条时间线上。
29. As an 操作者, I want 录制默认关闭、通过点亮录制器方块按需开启, so that 快速调试不产生数据堆积。
30. As an 操作者, I want 每次启动都自动创建 run 目录并留存节点日志、metadata 与事件文件, so that "没录 mcap"不等于"什么都没留"。
31. As an 诊断者, I want 开录时 MCAP 覆盖全部公开 topic 与 /rosout, so that 节点告警日志也在证据链里。
32. As an 诊断者, I want metadata 记录方块清单、起始模板、参数快照、git commit、USB 设备与模式侧别, so that 离线分析时确切知道当时跑的是什么。
33. As an 诊断者, I want 在网页上随时打时间标记并连同方块中途启停事件写入事件文件, so that 事后分析有锚点。
34. As an 诊断者, I want 1Hz 的 CPU 与内存采样进入 run 目录, so that "卡顿其实是机器满了"可以被证实或排除。
35. As an 诊断者, I want 仅凭一个 run 目录就能离线定位链路数据中断的责任环节, so that 不需要复现现场。
36. As an 操作者, I want run 历史页显示各 run 大小并支持手动删除, so that 磁盘管理是显式动作。
37. As an 操作者, I want 网页不暴露 arm/disarm/clear_fault, so that 唯一让真机动起来的授权仍由我在终端显式完成。
38. As an 操作者, I want 编排器无论以何种方式死亡所有节点都跟随退出, so that 控制面崩溃不会留下真机悬空运行。
39. As an 维护者, I want 单实例锁防止第二个编排器启动, so that 不会出现双编排器抢管节点。
40. As an 诊断者, I want 数据链路模式（只启动接收与重定向，数据到 command 为止）, so that 不碰硬件就能验证手套到重定向的质量。
41. As an 诊断者, I want 合成输入源以确定性假帧灌入 UDP, so that 零硬件也能复现与回归重定向行为。
42. As an 诊断者, I want 全链路 sim 模式用软件 provider 替代硬件 provider, so that 无真机也能跑通完整链路。
43. As an 维护者, I want 真机模式的编排配置被禁止引用 system_test 包, so that 真机会话绝不加载测试代码。
44. As an 维护者, I want bash 一键脚本的 preflight 与进程管理逻辑全部迁入 Python 编排器, so that 编排只有一套真相。
45. As an 维护者, I want launchpad 作为独立包进入架构文档、依赖 DAG 与门禁测试, so that 工具本身也受架构治理。
46. As an 测试开发者, I want 通过 HTTP/WebSocket API 黑盒配合替身进程测试编排行为, so that 测试不依赖 ROS 真节点且崩溃注入可确定性复现。
47. As an 测试开发者, I want 复用 system_test 真节点图验证状态灯与面板语义, so that UI 展示对的是真实状态消息。
48. As an 验收者, I want v1 硬标准是全程仅靠网页完成真机会话且能离线定位注入故障, so that 需求是真的达成而不是看起来达成。

## Implementation Decisions

### 包落位与技术栈

- 新建独立 Python 包 `rokoko_omnihand_launchpad`，置于 `src/collection` 下与 `omni_hand` 平级；不并入 bringup（bringup 保持刻意极薄的定位）。
- 后端：FastAPI + uvicorn + rclpy 同进程，rclpy 以后台线程 spin；运行于 ROS Jazzy sourcing + 数值 mamba 环境的混合环境（与现有 system_test 测试同模式）。
- 前端：Vite + Vue3 + ECharts；`npm run build` 产物不进 git，由构建脚本生成。
- 访问：本机浏览器，绑定 127.0.0.1，无鉴权，UI 中文，默认端口 8710；单实例锁防双开。

### 两级启动与编排器

- 一键脚本只启动控制面；业务节点全部由编排器以子进程方式直接管理（沿用已验证会话的 4 进程组合与启动方式，含"重定向节点必须以源码 wrapper 启动"的环境约束），不复用也不修改 production launch 文件。
- bash 脚本的 preflight 逐条迁入编排器：ros2 可用性、数值环境可 import 关键库、参数档案存在、节点查重、条件化的 USB-CANFD 设备检测与合成源生成器检查；bash 脚本退役。
- 进程安全：全部业务进程为编排器子进程并设置 Linux PDEATHSIG——编排器以任何方式退出（含 kill -9），节点全部跟随退出。
- 崩溃只检测告警，不自动拉起（硬件链路中途自动复活有安全风险）。

### 方块网格与模式模板

- 七个方块：`rokoko_receiver`、`hand_retargeting`、`omnihand_o10_control`、`hcan 真机 provider`、`sim provider`、`合成输入源`、`录制器`；前四个为业务节点样式，后三个为工具样式。
- 方块亮 = 期望运行；同一张网格贯穿启动配置与运行控制，运行中点击即启停该进程（停止带下游影响提示）。
- 模式模板 = 预点亮集合：真机 = [receiver, retargeting, control, hcan]；数据链路 = [receiver, retargeting]；全链路 sim = [receiver, retargeting, control, sim]。选择模板后可自由增删。
- 合成输入源方块取代独立的输入选择：亮 = 确定性假帧（复用 system_test 场景生成器）灌入 UDP；灭 = 等待真实 Rokoko 流。
- 侧别（双侧默认 / 仅左 / 仅右）为独立选择器，决定硬件通道绑定、录制范围与状态面板范围。
- 录制器方块默认熄灭（对应"默认不录"）。

### 组合校验规则

1. hcan provider 与 sim provider 互斥，同亮硬阻止（唯一硬规则：两者发布同一反馈 topic）。
2. 合成输入源 + hcan provider 同亮：红横幅 + 二次确认（不戴手套驱动真手的显式决定）。
3. 合成输入源点亮：黄提示 UDP 混流风险（同一端口两路数据）。
4. 孤儿组合（control 无 provider、retargeting 无 receiver 等）：不阻止，黄提示"将无上游而超时"。
5. preflight 随方块集条件化。

### 配置模型

- 预设档案 YAML 置于 bringup 包内 launchpad 专属目录；真机基线档案进 git（取自已验证真机会话的参数值），本地实验覆盖不入 git。
- 网页配置面 = 模板按钮 + 方块网格 + 侧别选择器 + 档案下拉 + 少数关键参数（UDP 端口、actor 序号、CAN 通道）；60+ 业务调参不进表单，改档案即编辑 YAML。
- production launch 文件的无默认值哲学不变。

### 状态监控

- 三级灯：绿 = 业务就绪（receiver：raw_hand 流动；retargeting：phase==TRACKING 且 command_published；control：O10ControlState 无 fault；provider：joint_states 流动）；黄 = 进程活着但业务未就绪（如指长收集中）；红 = 进程死亡或数据超时。
- 判活靠后端 topic 频率探测（阈值按各 topic 预期频率设定），零业务节点改动，不新增状态 topic。
- 状态推送约 5Hz，图表数据约 10Hz 下采样。

### 数据流面板

- 每侧四面板：10 关节目标 vs 反馈曲线（可叠加限幅后 joint_cmd）；重定向 phase 时间线 + 五指 IK 状态色带 + 残差曲线；topic 频率 + 端到端延迟逐跳分解（时间戳链已具备）；fault 状态 + 实时事件流。
- 不做 3D 手部可视化（v2 再议）。

### 录制与 run 会话

- 每次启动创建 run 目录 `runs/launchpad/时间戳_模板名或custom[_label]/`：节点日志（各进程 stdout）、metadata（方块清单、起始模板、参数快照、git commit、USB 设备、模式与侧别）、events（网页打标 + 方块中途启停）总是留存。
- 开录后追加：ros2 bag MCAP 录制覆盖全部公开 topic（两侧 raw_hand、retargeting state、command、O10ControlState、joint_cmd、joint_states、joint_error_states）与 `/rosout`；外加 1Hz CPU/内存采样的 sysmon 文件。
- 已知缺口（接受）：receiver 的 UDP 错误计数仅存在于日志（靠 /rosout 覆盖）；service 调用不可录（靠编排器自身操作日志补偿）。
- 无自动清理；run 历史页显示大小、手动删除。

### 架构治理

- 两份 ADR：其一修订既有"生产 composition 不含测试 Provider"不变量的边界——真机模式的编排配置禁止引用 system_test 包，mock 模式允许复用其软件 provider 与场景生成器；其二定义 launchpad 作为设备编排层的定位与依赖方向（launchpad → 四个业务包 + system_test 仅 mock 模式引用）。
- ARCHITECTURE.md 的包职责表、依赖 DAG、Port/Adapter 表同步更新；架构门禁测试补充对应规则。

### 分期

- M1：编排器 + 方块网格生命周期 + 三级灯 + 数据链路模式（含合成输入，兼作 web 工具自身的无硬件开发环境）。
- M2：录制全家桶（MCAP + /rosout + metadata + events + sysmon）与 run 历史。
- M3：数据流四面板。
- M4：全链路 sim provider 模式。

## Testing Decisions

- 好测试只断言外部可观察行为：API 响应、进程事实（存在/退出）、文件产物（run 目录内容）、灯与面板输出；不测编排器内部函数，不 mock 内部结构。
- 双接缝，测试只从这两处进入：
  1. 主接缝（新，最高层）：launchpad 的 HTTP/WebSocket API 黑盒。被拉起的业务节点用替身可执行进程代替（可控启动延迟、可注入崩溃、可发布假状态消息）。覆盖：组合校验五条规则、全启动/全停/重启/单节点启停、PDEATHSIG 与编排器 kill -9 跟随退出、run 目录产物、录制编排、metadata 与 events 内容。不依赖 ROS 真节点，确定性、快速。
  2. 次接缝（复用现有）：system_test 真节点图（合成 UDP → 真 receiver + 真 retargeting + 软件 provider）。覆盖：三级灯的业务语义、面板指标对真实 RetargetingState/O10ControlState/raw_hand 数据的正确性。
- 先例：主接缝对齐仓库既有的"公开接口黑盒"测试传统（真节点图测试、production launch 结构测试）；验收阶段用 acceptance-testing 流程做真机取证。
- 分期验收：每期架构门禁全绿 + acceptance 式取证。v1 硬标准：一次真机会话全程仅通过网页完成启动 → 监控 → 开录 → 停止；且事后仅凭 run 目录离线定位一个人为注入的故障（如中途 kill 掉 provider 或断开 UDP 流）。

## Out of Scope

- 3D 手部可视化。
- 网页暴露 arm/disarm/clear_fault 或任何授权操作。
- 节点崩溃自动拉起与自动恢复。
- receiver UDP 错误计数的 topic 化（涉及业务节点改动，v2 再评估）。
- 60+ 业务参数的网页表单编辑。
- 录制自动清理、保留策略与配额。
- 鉴权、多用户、局域网默认开放（绑定 127.0.0.1）。
- Foxglove/rosbridge 等外部可视化工具集成。
- production launch 文件的改造或替换。
- 真机参数的重新标定（基线档案沿用已验证值）。

## Further Notes

- 术语对齐：run 目录中的 MCAP 产物即用户概念体系中 collection 阶段的 raw MCAP；metadata/events/sysmon 是其伴随工程产物，run 目录构成一次 collection 会话的结构化边界。
- 与 01 spec 的关系：01 定义遥操作链本身；本 spec 定义其编排、监控与录制工具层。两者的接口边界是公开 topic 与进程事实，launchpad 不侵入业务节点。
- 实现期设计自由度（不需重新对齐的默认值）：端口 8710、探测超时阈值、推送节流频率、单实例锁实现方式、替身进程形态、前端组件划分。
- 本 spec 源自一场 grilling 会话的全部已确认决策（两级启动、全自研架构、方块网格模型、三级灯、录制证据集、双接缝测试、M1–M4 分期、注入故障离线定位的验收硬标准）。
