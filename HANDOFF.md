# 交接文档：Rokoko 手套 → O10 重定向 IK 残差故障判别（会话延续）

> 生成日期：2026-08-17。本交接面向"继续本次 IK 故障判别工作"的会话。
> 前序真机状态背景见根目录 `handoff-2026-08-14-rokoko-o10-command.md`，本文件只补充 8-14 之后新增的内容，不重复其历史。
>
> **状态更新（8-17 真机会话后）**：判别已完成并出正式报告 [DOCS/03_工程/07_真机IK残差失败判别报告.md](DOCS/03_工程/07_真机IK残差失败判别报告.md)（已登记 INDEX.md）。裁决：**原因 A（几何不可达）**，子类 A-dir 为主（53/60）+ A-under 深弯曲（4）+ A-ext（3）；B 为次要伴随（9/60 帧多起点改善但下限仍≫0.05）；C 排除。根因：目标生成公式把人类指尖弦向量直接映射，机械手折返半径（0.42~0.64）与可达面维度（1-2 DOF）远小于人手姿态空间。**下一步是修复方向的 spec/tickets，不是继续判别。**

## 任务目标（下一会话要完成的事）

判别工作**已完成**（见顶部状态更新）。下一会话的焦点是：根据报告 §6 建议，产出一份修复 spec（`to-spec`）并拆 tickets（`to-tickets`），首选方向为"目标生成处引入可达性投影（裁剪折返比 + 方向锥投影）"；次要 ticket：stale 恢复死锁（报告 §5，会话 stale 后因五指永不全有效而无法退出 recovery-confirming，需重启节点）。

## 问题背景（一句话）

五根手指必须全部有有效 IK 解才发布 `/o10_control/left/command`（`session.py:303` 全指 committed 非 None）；拇指/无名指/小指残差 > 0.05 且从未有过有效解 → 整侧永不发布。要判别失败原因是 A 几何不可达 / B 局部极小 / C 近奇异。

## 本会话已完成（全部验证通过）

| 产物 | 路径 | 状态 |
| --- | --- | --- |
| 真机录制脚本（JSONL + 姿态标记 stdin） | `src/collection/omni_hand/hand_retargeting/scripts/record_retargeting_session.py` | 已用 8-14 抓包数据干跑验证，标记功能端到端通过 |
| 离线判别器（重放 + T1 multi-start / T1b 预算 / T2 全局网格 / T3 驻点 KKT+SVD，输出 diagnosis.json/md，支持 matplotlib 3D 图） | `src/collection/omni_hand/hand_retargeting/scripts/ik_failure_diagnose.py` | `analyze`/`selftest` 两个子命令均验证 |
| 测试（9 纯单测 + 3 真实资产 opt-in，含 marker 切段测试） | `src/collection/omni_hand/hand_retargeting/test/test_ik_failure_diagnose.py` | 12 passed；flake8 同配置干净 |
| 实验参数 YAML（graph.py 实验值：阈值 0.05×5、预算 100 evals/0.02s、窗口 3/2、nmad 0.01、frozen-rel 0.10） | `runs/retargeting_diag_params.yaml`（runs/ 已 gitignore） | 复制自 /tmp，真机会话用此文件 |
| 干跑产物（8-14 真实左手数据 180 帧 + 判别结果） | `/tmp/dryrun/`（session_left.jsonl、diag/、diag_poses/） | 临时目录，重启会清空，可重新生成 |

## 关键结论（8-14 抓包静态姿态的初步裁决，动态多姿态待真机确认）

**已由真机数据确认（见报告 07）**：A 几何不可达为主因（60/60 样本），子类 A-dir 53 / A-under 4 / A-ext 3；B 是次要伴随（9/60 帧）；C 排除。根因：目标生成 `t = root + ℓʳ·A_s·(Tip−Proximal)/ℓ_h` 直接映射人类指尖弦向量，而机械手折返半径（min ratio 0.42~0.64）与可达面维度（1-2 DOF 窄带）远小于人手姿态空间——弯曲姿态（‖u‖ 低至 0.05）目标深入"折不进去"区，直指姿态方向偏离可达面。旁证：v1 出现过 587 帧 tracking 且 command 587/587 发布，证明链路本身可发布；v2 全程 recovery-confirming 死锁（次生问题，见报告 §5）。

## 真机会话操作（用户已被告知，下一会话可复用）

- 三个终端（公共准备见下）；receiver：`ros2 run rokoko_hand_receiver rokoko_hand_receiver_node`；retargeting：**必须用源码 wrapper**（见"环境坑"）；recorder 前台运行，姿态开始瞬间在 recorder 终端输入 `P0`/`P1`/`P2`/`P3`/`P4a`/`P4b`/`P4c`/`P5-ring`/`P5-little`/`P6`/`P7` 打标记，每个姿态保持 8~10 秒。
- 公共准备：`source /opt/ros/jazzy/setup.bash`、`source .../install/setup.bash`、`DEXHIT_COLLECTION_PREFIX=/home/hit/miniforge3/envs/dexhit_collection`、`OMNIHAND_O10_MODEL_FIXTURE=/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009`。
- 停止条件：节点崩溃 / raw_hand 断流 / 意外 `command_published=true`（记录后停）。

## 离线分析命令（拿到 JSONL 后执行）

```bash
OMNIHAND_O10_MODEL_FIXTURE=/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009 \
PYTHONNOUSERSITE=1 \
PYTHONPATH="/home/hit/miniforge3/envs/dexhit_collection/lib/python3.12/site-packages" \
LD_LIBRARY_PATH="/home/hit/miniforge3/envs/dexhit_collection/lib" \
/usr/bin/python3.12 src/collection/omni_hand/hand_retargeting/scripts/ik_failure_diagnose.py analyze \
  --jsonl runs/session_left.jsonl --side left \
  --params runs/retargeting_diag_params.yaml \
  --out runs/diag_left
```

输出 `diagnosis.json` + `diagnosis.md`（含 Pose segments 与逐样本裁决表）；加 `--plots` 生成可达面 3D 图（需 matplotlib，mamba env 未验证装有，缺则跳过）。

## 环境与部署坑（必须遵守）

- **colcon 本机不存在**（任何环境都没有）；`colcon build/test` 走文档化路径时会失败——全局测试需改用 mamba env + pytest 直跑（见测试命令），或提示用户先装 colcon。
- **install/ 入口脚本是旧版 console_scripts shim（8-14 16:03）**，不含工作树 wrapper（BLOCKED_ENV 检查）；**不要用 `ros2 run hand_retargeting hand_retargeting_node`**。真机用源码 wrapper：`bash src/collection/omni_hand/hand_retargeting/scripts/hand_retargeting_node --ros-args --params-file <yaml>`（已验证可跑；Python 代码本体经 egg-link 指向 build space，与工作树一致）。
- 节点被 SIGTERM 时打印无害 traceback（rclpy ExternalShutdownException），属正常现象。
- 直跑 pytest 缺 `ament_flake8`/`rclpy` 时，`test_flake8.py`/`test_pep257.py`/`test_retargeting_node.py`/`test_runtime_entrypoint.py` 收集报错属环境差异，非本会话改动引入；lint 用 mamba env 的 flake8 + 包内 ament_flake8.ini 配置手动跑。
- 工作树未提交改动（nlopt.py/session.py/ik.py/setup.py 及 t06 测试等）是 8-14 既有的，不属于本会话；本次新增仅 `scripts/`（两个脚本）与 `test/test_ik_failure_diagnose.py`，均未注册安装、不进 production launch。Git 规则：用户未要求则不 commit。

## 建议技能（Suggested skills）

- `diagnosing-bugs`：真机数据出裁决表后，若出现与初步结论不符的姿态，用它做进一步根因分析；
- `code-review`：对本次两个诊断脚本 + 测试做最终合入前审查；
- `to-spec` 或 `to-tickets`：若结论需要改目标生成/IK 策略（如 A-dir 修复方向：目标生成引入可达面投影、或调整 ℓʳ 定义），把修复拆成 tickets；
- `tdd`：实施任何修复时按仓库 TDD 规则推进。
