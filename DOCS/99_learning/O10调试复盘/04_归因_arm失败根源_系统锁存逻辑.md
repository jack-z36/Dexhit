# 归因 ④（✅ 第一次确认）：arm 失败根源 = 系统锁存逻辑把历史标记当致命故障

> **结论：✅ 确认并修复。** 屏蔽 bit4（commu_except）后 arm 成功——这是 4 个叠加问题里最先被钉死的一个。

## 1. 观测（看到了什么）

- 前三轮把外因全排除了：通信没断、读数工具是 bug、官方说 bit4 正常。
- 但 arm 依然被拒，返回 `fault is latched`。

```
已排除：
  ✗ 硬件通信坏        （位置/温度/电流可读）
  ✗ 整手 8 关节异常    （批量接口 bug 放大）
  ✗ commu_except 是致命（官方定义：历史标记，正常）

剩下的嫌疑：系统自己
```

## 2. 推测（重新定位）

**当所有外因都被否定，问题一定在系统自身的"加工逻辑"。**

系统把"错误字 & 任何错误位 != 0"当成锁存条件，等于把"官方说正常的历史标记"当成了"致命硬件故障"。

## 3. 验证（怎么证明）

- 在契约层定义清楚两类位：
  - `VENDOR_ERROR_BIT_COMMU_EXCEPT = 1 << 4`（可忽略）
  - `FATAL_ERROR_BIT_MASK = 0xFFFF & ~VENDOR_ERROR_BIT_COMMU_EXCEPT`（真实硬件故障才锁存）
- 把锁存判断改为 `错误字 & FATAL_ERROR_BIT_MASK != 0` 才锁存。
- 补 3 个单元测试：纯 bit4 不锁存；bit4+真实位仍锁存；clear_fault 忽略 bit4。

## 4. 结果（验证怎么说）

- ✅ 单元测试全过（contracts 103 + control 34 + hardware 23）。
- ✅ **真机 arm 成功**：
  ```
  success=True  message="armed"  fault_latched=False
  motion_enabled=True  feedback_ready=True  target_ready=True
  ```

## 5. 结论与教训

> 教训④：**当所有外因都被否定，回到系统自身逻辑找"加工错误"**。硬件没问题时，问题常常出在"我们对数据的解读"上。

## 6. 衔接下一轮

arm 成功了！但紧接着新现象出现：**手还是不动**。→ 进入 [归因⑤](05_归因_手不动是SDK配置错.md)。
