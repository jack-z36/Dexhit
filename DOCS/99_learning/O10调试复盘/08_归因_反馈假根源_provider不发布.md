# 归因 ⑧（✅ 第三次确认）：反馈不就绪根源 = provider 缺周期发布（架构缺口补齐）

> **结论：✅ 确认并修复。** provider 增加 0.5 秒周期发布 joint_states，`feedback_ready=True`。文档预告过的架构缺口，真机上兑现了。

## 1. 观测（看到了什么）

- 确认 provider 从不发布 joint_states（归因⑦ 已验证）。
- 控制会话的"反馈就绪"永远等不到消息。

## 2. 推测（重新定位）

**不是 control 算错，是 provider 缺一个职责：周期读取关节状态并发布。**

原设计里 provider 是单线程 `rclpy.spin(node)`，只处理命令和错误查询，**没有发布关节反馈的定时任务**。

## 3. 验证（怎么证明）

- 修复：在 provider 节点里加一个 0.5 秒周期定时器，周期读取关节状态并发布 `joint_states`：
  ```python
  self._feedback_timer = self.create_timer(0.5, self._publish_feedback_periodic)
  ```
- 重新构建 → 重启 provider → 观察控制会话。

## 4. 结果（验证怎么说）

- ✅ 反馈开始流动，控制会话 `feedback_ready=True`。
- ✅ 真机链路完整：
  ```
  feedback_ready=True  target_ready=True  motion_enabled=True
  ```

## 5. 结论与教训

**架构文档里写"未实现"的缺口，真机上一定会变成真问题。** 补职责比修表象重要——provider 本来就该发布反馈，而不是让 control"将就"。

> 教训⑧：看到"永远等不到"的异常，先查**数据源头有没有这个职责**。文档预告的缺口，就是未来故障的预告片。

## 6. 衔接下一轮

链路基本通了，但最后一步还有个小问题：**read 服务报 pinky_abad 超限**。→ 进入 [归因⑨](09_归因_超限是读数异常.md)。
