# 真机接入诊断测试计划：判别 IK 残差失败三假设（A 几何不可达 / B 局部极小 / C 近奇异）

## 0. 已确认的链路事实（计划依据）

- **不发布机制**：`session.py:303` 要求 5 指 `committed` 全非 None；拇指/无名/小指**从未**有过一次有效解 → 整侧永不发布 `/o10_control/left/command`。
- **目标生成**（`session.py:145-153`）：每指 1 个 3D 位置目标 `t = root + ℓʳ·A_s·(Tip−Proximal)/frozen`，其中 `(Tip−Proximal)/frozen` **非单位向量**（‖u‖≤1，弯曲时变小）。
- **DOF 与阈值**：T=3 / I=2 / M=1 / R=2 / L=2 个主动 DOF 对 3D 目标；残差 = ‖FK_tip − t‖/ℓʳ，阈值 `ik_residual_thresholds`（0.05，来自生产 YAML，不在代码写死）。
- **优化器**：NLopt SLSQP（`nlopt.py`），初值 = 限位中点（首解前）或上一有效解 warm-start；预算 `ik_max_evaluations/ik_max_time_sec` 来自 YAML。**无 multi-start、无日志**。
- **关键注入缝（零侵入录制）**：`RetargetingSession.__init__` 接受注入 `optimizer`（session.py:85）；`FingerProblem` 自带 target/lower/upper。离线重放可用 RecordingOptimizer 包装真实 `NloptSlsqpOptimizer`，逐帧捕获与线上**完全一致**的问题。`RetargetingState` 话题有 residual/result_code 但无 target，故目标必须靠重放再生。
- **重要前置风险**：工作树有未提交的 `nlopt.py` 改动（ROUNDOFF_LIMITED 时保留候选）。必须先确认运行安装版本 = 工作树版本，否则线上表现（residual-exceeded vs solver-error）不可解释。
- **结构性先验**（最终以数据裁决）：R/L 只有 2 DOF + 单侧窄 abad 限位（ring [0,0.1693]，pinky [0,0.1850]），3D 目标一般不在可达面上 → A 结构性嫌疑大；且 ℓʳ 按零姿态**路径长**定义 > 直线最大伸展，直指目标可能结构性超伸。拇指 0.19 与已知交接案例 0.225 同型。食指 abad 限位符号（[-0.164,0]）与 ring/pinky 相反——若左右手/侧接错，会精确产生"食指过、无名/小指挂"的指纹。

## 1. 判别逻辑（核心实验设计）

对每个失败样本（指 f × 帧 k）执行四项测试，填决策矩阵（τ = 生产阈值）：

- **T1 Multi-start（判 B）**：64 个 Sobol 随机初值 + 确定性集 {中点、各角点、零位截断}，同一预算；`r_ms` = 最优残差。
- **T1b 预算敏感性（排除第 4 原因）**：同中点初值，预算 ×10 → `r_single_relaxed`。防止把"评估预算不足"误判进三假设。
- **T2 全局网格可达集（判 A）**：R/L/I 用 1201² 网格、M 用 4001、T 用 101³+两级局部细化（Pinocchio FK 离线可承受）；`r_grid` = 全局最小残差，同时记录 max_reach、最近流形点 q*、误差向量 e* 的分解（沿链伸展向 vs 垂直可达面）。
- **T3 驻点诊断（判 C）**：在单起点停止点 q_stop 计算 ‖Gᵀe‖（投影梯度）、边界 KKT 残差、σ_min(G)/σ_max(G)（G = Pinocchio 全雅可比 × 耦合雅可比）。

**决策矩阵**：

| r_single | r_ms | r_grid | σ_min(q_stop) | 裁决 |
|---|---|---|---|---|
| >τ | ≤τ | ≤τ | 任意 | **B 局部极小** |
| >τ | >τ | >τ（≈r_ms） | 任意 | **A 几何不可达**（全局下限>τ） |
| >τ | ≤τ | ≤τ | 小 | **B，C 为被困机制** |
| >τ | >τ | ≤τ | — | 起点数/算法不足，加密 multi-start 重判 |
| r_single_relaxed ≤τ | — | — | — | **预算不足**（非 A/B/C） |

**A 的子类分解**（决定后续修复方向，完全不同）：
- **A-ext 超伸**：‖t−root‖ > 网格 max_reach（ℓʳ 路径长 vs 直线伸展的结构性缺口）；
- **A-dir 方向偏离**：伸展够但目标不在可达面上（2-DOF 指结构性 / abad 限位 / A_s 映射）；
- **A-upstream 上游 bug**：冻结长度异常、‖u‖ 分布异常、左右手侧/A_s/限位符号接反。

**T4 目标侧体检**（A 裁决时执行）：冻结长度 vs 解剖合理值；‖u‖ 分布（直指≈1、弯曲<1）；side 靶向检查（掌系中 ThumbProximal 的 X 符号 vs JOINT_LIMITS 左侧符号）；每指可达面 + 真实目标云 3D 散点图（PNG 证据）；拇指对比 0.225 已知案例。

## 2. 新增工具（不改任何业务代码/消息/launch）

1. **`hand_retargeting/scripts/record_retargeting_session.py`**（rclpy，约 80 行）：订阅 `/rokoko/left/raw_hand` + `/hand_retargeting/left/state` → JSONL（帧+状态+接收时间）。分析主输入；同时并行 `ros2 bag record` 存档。
2. **`hand_retargeting/scripts/ik_failure_diagnose.py`**（离线，无 ROS 依赖，mamba env + OMNIHAND_O10_MODEL_FIXTURE）：
   - 输入 JSONL + 生产参数 YAML + side=left；
   - 用真实 coupling/kinematics/优化器 + RecordingOptimizer 重放 `RetargetingSession`，逐帧捕获 (problem, initial, result)；**有效性断言：离线残差 ≈ 线上录制残差（容差内），证明重放可信**；
   - 对失败样本跑 T1/T1b/T2/T3 → JSON + Markdown 结果表 + PNG 可视化。
3. **测试 `hand_retargeting/test/test_ik_failure_diagnose.py`**（与 test_t06_real_assets.py 同款 opt-in）：可达合成目标 → 裁决非 A；不可达合成目标 → 裁决 A；multi-start/网格逻辑用 fake kinematics 纯单测。
4. 脚本从源码运行、不注册安装、不进 production launch；测试代码进 git，运行输出不进 git（编程执行规则 §12）。

## 3. 真机会话 runbook（你戴左手手套执行；最小拓扑：receiver + hand_retargeting，无 o10_control/硬件）

**L0 预检（无手套，先做）**：
- 确认 mamba env（python3.12 + pinocchio 4.1.0 + nlopt 2.11.0）、`OMNIHAND_O10_MODEL_FIXTURE`、`DEXHIT_COLLECTION_PREFIX`；
- `git status` 快照；确认已安装构建 = 工作树（未提交的 nlopt.py 修复必须在运行版本里），必要时 colcon rebuild；
- 离线冒烟：跑 `test_t06_real_assets.py` + 诊断脚本自测（合成可达/不可达两例）；
- 备好生产参数 YAML 路径（离线重放必须逐值同参）。

**L1 启动**：仅起 receiver + hand_retargeting（用生产参数 YAML）；开 JSONL 录制 + bag 录制；验证 `/rokoko/left/raw_hand` 频率；观察 phase 走到 `WAITING_FIRST_VALID_IK`、五指长度冻结。

**L2 姿态脚本**（每姿态静止保持 8–10 秒，口头报时间戳便于对齐）：
- P0 平放静手（长度冻结 + 基线残差）→ P1 平放最大展指 → P2 半握拳 → P3 全握拳 → P4 拇指三静止位（触食指根/内收/外展）→ P5 无名指单独慢屈×3、小指单独慢屈×3 → P6 自然随意 30s → P7 回到 P0（看 warm-start 重锁）。
- 每姿态观察点填表：各指 `ik_state`、`normalized_residual`、`solver_result_code`、`solver_evaluations`、`phase`、`command_published`。

**停止条件**：节点崩溃、raw_hand 断流、意外 `command_published=true`（记录后停）。**L3**：停节点/录制，保存 JSONL + bag + 参数 YAML 副本。

## 4. 离线分析流程

O1 解 JSONL → 帧序列 + state 对照；O2 重放并断言残差一致（≥95% 帧容差内，否则先查版本/参数不一致）；O3 逐失败样本（每姿态抽 ~20 帧）跑 T1/T1b/T2/T3；O4 A 样本做 T4 + 可视化；O5 汇总：每指一行决策矩阵 + 数值证据表。

## 5. 交付物

1. **判别报告** `DOCS/03_工程/06_真机IK残差失败判别报告.md`（三假设逐指裁决 + A 子类 + 证据链 + 后续建议，不含修复实施），按文档维护规则更新 `DOCS/03_工程/INDEX.md`；
2. 两个诊断脚本 + opt-in 测试；
3. 按编程执行规则 §11 记录：工作目录、命令、fixture、观察点、已验证/未验证边界（本次只验证 receiver+retargeting，不宣称任何真机硬件验证）。

## 6. 验收标准

- 重放有效性：离线残差与线上一致（≥95% 帧）；
- 拇指/无名指/小指各得到明确裁决（A/B/C 或混合，附数值与可视化证据）；
- A 裁决必须落到子类（A-ext / A-dir / A-upstream）；
- 全程不触发真机动作（最小拓扑保证）。

## 7. 执行顺序

先实现并离线验证工具（含测试）→ 你接入手套跑 L0–L3 → 我做 O1–O5 → 出报告。工具开发不依赖手套，可立即开始。