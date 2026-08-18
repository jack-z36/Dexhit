# 归因 ⑥（✅ 第二次确认）：手不动根源 = control 命令缺 name 字段，provider 按契约拒收

> **结论：✅ 确认并修复。** provider 日志直接抛出拒收理由：命令的 `name` 字段是空的。补上关节名后，**手真的动了**。

## 1. 观测（看到了什么）

- 正在困惑手为什么不动时，**provider（硬件适配层）的日志主动抛出了一行硬证据**：
  ```
  command name must use the fixed O10 active-joint order
  ```
- 翻译：你发的命令里 `name` 字段不符合要求，按规矩**拒收**。

## 2. 推测（重新定位）

**问题不在 SDK，在 control（控制层）转发的消息本身。**

链路是这样的：

```
control 转发 joint_cmd ──▶ provider 检查契约 ──▶ SDK ──▶ 硬件
                              │
                              └─ name 为空 → 拒收（手当然不动）
```

`build_command_message` 构造的命令，`name` 字段是空的（`[]`），而 provider 的契约要求：必须带固定的 10 个活动关节名，顺序还不能乱。

## 3. 验证（怎么证明）

- 读 `ros_convert.py` 的 `build_command_message`：确认 `name` 确实没填。
- 修复：`result.name = list(ACTIVE_JOINT_NAMES)`（固定顺序的关节名）。
- 重新构建 → 重启节点 → 真机发目标。

## 4. 结果（验证怎么说）

- ✅ 手真的动了：
  ```
  thumb_abad: -0.007 → 0.138 → 0.168（拇指展开）
  index_pip:   0.015 → 0.164 → 0.195（食指弯曲）
  ```
- ✅ 运动是平滑的——限速器（0.1 rad/s）把大目标切成小步长，属正常安全行为。

## 5. 结论与教训

**消息契约里一个字段都不能缺**：provider 严格检查 `name`，缺了就整个拒收，跟硬件无关。

> 教训⑥：**让日志说话。** provider 的拒收理由比任何猜测都快、都准。排查时先看"被拒收的地方"打印了什么，而不是先怀疑下一层（SDK/硬件）。

## 6. 衔接下一轮

手动了！但控制会话又报新现象：**feedback_ready 永远 false**。→ 进入 [归因⑦](07_归因_反馈假是control逻辑错.md)。
