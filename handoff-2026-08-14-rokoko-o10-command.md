# Handoff：Rokoko → O10 遥操作系统（重定向节点 command 输出验证）

**日期**：2026-08-14
**分支**：`collection`（工作区 `/home/hit/Dexhit-worktrees/collection`，注意是 worktree）
**一句话状态**：`rokoko_hand_receiver` 已真机跑通；`hand_retargeting` 节点能启动、`/o10_control/{left,right}/command` topic 已创建，但 **command 无数据**，停在 `PHASE_MODEL_ERROR`，根因是运行环境缺 pinocchio / nlopt / 模型资产。

---

## 目标数据流

```
Rokoko Studio (UDP 14043, LZ4 JSON v3)
  → rokoko_hand_receiver  → /rokoko/{left,right}/raw_hand   (RawHandFrame)
  → hand_retargeting      → /o10_control/{left,right}/command (sensor_msgs/JointState, 10 关节)
                           → /hand_retargeting/{left,right}/state (RetargetingState)
  → omnihand_o10_control  → （后续）
  → omnihand_o10_hardware_adapter → （后续，真机）
```

重定向节点发布 command 的代码位置：`src/collection/omni_hand/hand_retargeting/hand_retargeting/node.py:131-134`（创建 publisher）、`:245-251`（仅当 `decision.command_published` 时发布）。10 个主动关节名见 `src/collection/omni_hand/omnihand_o10_contracts/omnihand_o10_contracts/joints.py`。

## 已完成（引用现有 artifact，勿重复）

- **receiver 已真机验证通过**：LZ4 解压 + `version:"3,0"` 字符串判断。改动见 `src/collection/omni_hand/rokoko_hand_receiver/`（decoder.py、setup.py、package.xml、fixtures、测试）。35 个测试全过。**尚未 git commit**（见下「git 状态」）。
- 规格/架构/接口契约/tickets 均在 `DOCS/` 下，新 agent 应直接读：
  - 总览：`DOCS/01_知识/00_项目总览.md`、`DOCS/03_工程/00_当前状态.md`
  - 架构与数据流：`DOCS/01_知识/ARCHITECTURE.md`、`DOCS/01_知识/01_模块边界与数据流.md`
  - ROS 接口契约：`DOCS/01_知识/04_Rokoko原始手部帧ROS接口契约.md`、`05_手部重定向状态ROS接口契约.md`、`06_O10控制状态ROS接口契约.md`
  - 算法基线：`DOCS/01_知识/03_人手归一化与O10单指IK算法基线.md`
  - **关键 ADR**：`DOCS/01_知识/ADR/0007-o10-versioned-minimal-runtime-model-assets.md`（模型资产 vendoring 被许可证阻塞，须用 `OMNIHAND_O10_MODEL_FIXTURE` 外部资产）；`0002-phase1-single-finger-ik-slsqp-analytic-gradient.md`（IK 用 NLopt SLSQP + 解析梯度）；`0009-phase1-owned-runtime-python.md`（运行期 Python 归因）。

## 本次会话的关键发现与修复

1. **install 空间是旧代码**：之前 build 的 `hand_retargeting` 无 command publisher（旧版 7 参数）。src 新版才有 command 发布。→ 已 `colcon build --symlink-install` 重建。
2. **build 误用 miniforge Python 3.13**（重要，会再次踩坑）：当前 shell 是 conda `(base)`，`PATH` 里 `/home/hit/miniforge3/bin` 排在 `/usr/bin` 前，导致 CMake 用 Python 3.13 编译 `rokoko_omnihand_msgs` 的 C 扩展（链接 `libpython3.13.so`），ROS 运行时 Python 3.12 import 即崩（`libpython3.13.so.1.0: cannot open shared object`）。
   - **修复命令**（重建时必须照做）：
     ```bash
     source /opt/ros/jazzy/setup.bash
     export PATH="/usr/bin:$PATH"           # 让系统 python3.12 优先
     colcon build --symlink-install --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3.12 -DPython3_ROOT_DIR=/usr
     ```
   - 已验证 `build/rokoko_omnihand_msgs/CMakeCache.txt` 里 `_Python3_EXECUTABLE=/usr/bin/python3.12`、`PYTHON_INSTALL_DIR=lib/python3.12/site-packages` 才算成功。

## 当前阻塞点（下一步要解决的核心）

重定向节点启动日志报：
```
cannot derive left O10 geometry from verified model assets: No module named 'pinocchio'
```
节点随即进入 `PHASE_MODEL_ERROR`（`RetargetingState.msg` 枚举 `PHASE_MODEL_ERROR=7`），`command_published=False`，command 永不发布。

要走通「长度采集 → 冻结 → 首次有效 IK → tracking → command」，需要三样环境里都没有的东西：

1. **pinocchio**（运动学）—— 未安装
2. **nlopt**（SLSQP 优化器）—— 未安装
3. **O10 真实模型资产**（URDF + MJCF + manifest.json）—— 未 vendored（ADR-0007），须通过 `OMNIHAND_O10_MODEL_FIXTURE` 指向带 SHA-256 校验的资产目录。loader 逻辑见 `src/collection/omni_hand/omnihand_o10_model/omnihand_o10_model/loader.py`。

候选真实资产位置（尚未验证是否符合 provenance 结构）：`/home/hit/dexhit相关开源项目/ManusOmniBridge/src/omnihand_description-O10/assets/`（含 `urdf/omnihand_left.urdf`、`omnihand_right.urdf`、`MJCF/`），但缺 manifest.json，且 SHA-256/commit 校验要求见 `omnihand_o10_model/provenance.py` 与 `contract.py` 的 `UPSTREAM_COMMIT`。

## 环境要点

- ROS `jazzy`；系统 Python **3.12**（`/usr/bin/python3.12`）；miniforge Python 3.13 在 conda base，会污染 PATH（见上）。
- 每个 `ros2` 终端都要 `source /opt/ros/jazzy/setup.bash` + `source install/setup.bash`，否则 `ros2 topic echo` 报 `message type ... is invalid`。
- 数据源持续在发：UDP `14043`，LZ4 压缩 JSON v3，约 2950 字节/帧，30fps。当前仅左手手套（`hasRightGlove=false`），右手每帧被 receiver 正常拒绝。
- 防火墙已放行 `14043/udp`（`sudo ufw status` 可见）。
- 用户终端里可能仍有一个 `rokoko_hand_receiver` 进程在跑（本次会话中 pid 717317）；测试时注意 14043 端口占用。

## 建议的下一步

1. 安装 pinocchio + nlopt 到**系统 Python 3.12**（勿装进 conda base）：`/usr/bin/python3.12 -m pip install pinocchio nlopt`。
2. 准备模型资产：按 ADR-0007 / `provenance.py` 生成 manifest，设置 `OMNIHAND_O10_MODEL_FIXTURE`，使 `load_model()` 校验通过。
3. 重新启动 `receiver` + `hand_retargeting`，观察 state 从 `PHASE_INITIALIZING` 逐步推进到 `PHASE_TRACKING`，并确认 `/o10_control/left/command` 有 JointState 数据。
4. （可选）把 receiver 的未提交改动 git commit。

## git 状态（未提交，尚未 commit）

- 已改：`rokoko_hand_receiver` 全套（decoder.py/setup.py/package.xml/fixtures/测试）
- 新增：`test/fixtures/captured_left_glove_v3.{json,lz4}`、`rokoko_test.py`（临时脚本，可删）
- 文档改动：`DOCS/03_工程/00_当前状态.md`、`INDEX.md`、若干新测试文档；`人手归一化算法细节设计：坐标系转换.md` 的删除/新增（本次会话未主动处理）

## suggested skills

下一个 agent 建议按需调用：

- `diagnosing-bugs` —— 继续定位「command 无输出」的环境依赖链路（若装完 pinocchio/nlopt 仍不通）。
- `research` —— 确认 pinocchio/nlopt 的正确安装方式（Ubuntu + Python 3.12）、以及 O10 资产 provenance/manifest 的生成方法。
- `tdd` —— 若要为「真实 pinocchio/nlopt 后端」补集成测试（现有 `hand_retargeting/test/test_t06_real_assets.py` 是 opt-in，需 `OMNIHAND_O10_MODEL_FIXTURE` + pinocchio + nlopt 才运行）。
- `code-review` —— 在把 receiver 改动 commit 前做一次规范/规格双轴审查。
