# O10 架构决策索引

本目录记录 OmniHand O10 控制链中难以逆转、具有真实取舍且仅看代码难以理解的架构决策。不记录普通实现选择、当前进度或测试结果。

- [O10 IK 以主动关节为唯一求解空间](0001-o10-active-joint-constrained-kinematics.md)：以 10 个主动关节求解，并显式派生 6 个被动耦合关节后计算运动学。
- [Phase 1 单指 IK 使用 SLSQP 与解析耦合梯度](0002-phase1-single-finger-ik-slsqp-analytic-gradient.md)：运行时使用 Pinocchio 完整指链雅可比与 MJCF 耦合雅可比组成的解析梯度，中心差分只作离线验证。
- [O10 最终命令使用反馈初始化的事件触发硬限速](0003-o10-feedback-initialized-event-driven-slew-limit.md)：以真实启动反馈和最后实际发送命令为基准，用单调时钟与封顶时间额度约束每关节命令变化率。
- [O10 真机运动需要逐侧显式操作者授权](0004-o10-explicit-per-side-operator-arming.md)：技术就绪不自动开始运动；每侧必须由操作者显式使能，解除使能只停止新命令。
- [区分可自动恢复暂停与锁存控制故障](0005-o10-recoverable-pause-vs-latched-fault.md)：人体输入暂时异常保留授权；硬件、通信和安全门异常撤销授权并要求人工清除和重新初始化。
- [stale 恢复使用连续整侧验证和既有两级平滑](0006-stale-recovery-validation-and-bounded-resume.md)：恢复必须满足连续整侧有效帧和最短观测时间，先重发保持目标，再由低通与硬限速逐步追赶。
- [O10 在线模型使用版本锁定的最小资产包](0007-o10-versioned-minimal-runtime-model-assets.md)：核心运行资产仅含左右 URDF、左右 MJCF 和 provenance；通过 ROS 安装空间加载、关闭 URDF mimic 并严格校验耦合。
- [O10 控制使用事件—效果边界接入可替换硬件 Provider](0008-o10-control-event-effect-hardware-port.md)：控制 Application 只处理纯事件和效果；生产厂商 Provider 与无真机纯软件 Provider 实现同一 O10HardwarePort wire contract。
- [Phase 1 自有运行包固定使用 Python 3](0009-phase1-owned-runtime-python.md)：自有运行代码统一使用 Python/ament_python，使框架边界和依赖门禁具有单一可执行语言范围；跨语言迁移必须先升级门禁。
- [O10 无动作主动关节读取使用逐侧 Service](0010-o10-fresh-active-joint-read-service.md)：生产与纯软件 Provider 通过同一逐侧 Service 在请求后执行无动作新读取，控制端拥有超时与复核。
