# ADR-0012：Launchpad 作为设备编排层

- 状态：Accepted
- 日期：2026-08-18
- 范围：`rokoko_omnihand_launchpad` 与 collection 阶段的 ROS 包

## 背景

遥操作系统的业务节点、硬件 Provider 和录制工具需要按一次会话的期望状态启动或
停止。把网页入口塞进 `rokoko_omnihand_bringup` 会让 production launch 既承担静态
composition，又承担交互式生命周期，最终形成两套启动真相。把控制面放进任一业务包
也会让业务包拥有设备编排状态，破坏模块边界。

## 决策

1. `rokoko_omnihand_launchpad` 是独立 `ament_python` 包，属于 Composition /
   External 层；其当前物理位置遵循 [ADR-0013](0013-collection-production-node-first-source-layout.md)，目录位置不改变本 ADR 的依赖和所有权决策。
2. 依赖方向为 `launchpad → rokoko_hand_receiver / hand_retargeting /
   omnihand_o10_control / omnihand_o10_hardware_adapter`；`launchpad →
   rokoko_omnihand_system_test` 仅允许在显式 mock 模式成立。业务包、Provider 和
   `rokoko_omnihand_bringup` 不得反向导入或依赖 Launchpad。
3. Launchpad 只拥有控制面配置、实例锁、进程生命周期和会话编排事实；业务节点继续
   拥有自己的 ROS 状态、算法、安全门和 Port。Launchpad 不复制这些业务状态，也不
   暴露 `clear_fault`（自 `4fedfaa` 起 arm/disarm 已移除，运动由目标直接驱动）。
4. T01 先落地 FastAPI/uvicorn 入口、前端脚手架和无业务副作用的占位页；业务进程
   adapter、模式校验和 ROS 图接入由后续 tickets 实现。

## 后果

- 控制面可以独立启动、测试和退出，生产 bringup 保持刻意极薄。
- HTTP/WebSocket 黑盒测试可以使用替身进程，不需要把测试依赖塞进业务包。
- 依赖图中 Launchpad 位于最外层；未来新增工具必须通过它或明确的 composition 边界
  接入，不能在业务节点中添加反向快捷路径。

## 未决事项

后续 tickets 需要确定业务进程 adapter 的精确命令、PDEATHSIG 实现和 ROS 状态探测
接口；这些实现选择不得改变本 ADR 的依赖方向和所有权边界。
