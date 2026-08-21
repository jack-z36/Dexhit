---
status: accepted
---

# O10 控制使用事件—效果边界接入可替换硬件 Provider

O10 控制 Application 以纯事件原子更新逐侧运动使能、故障和硬限速状态，并产出“读取主动关节、查询错误、发送命令、发布状态”等纯效果；ROS runtime 执行效果，再把真实结果作为新事件回送。生产厂商 Provider 与无真机纯软件 Provider 实现同一 O10HardwarePort wire contract，控制 Core/Application 不导入任一 Provider。这样既能通过完整 ROS 图测试真实控制状态机，又能防止厂商 SDK、测试替身和 ROS Future 泄漏进安全逻辑；代价是 runtime 必须显式处理效果执行成功/失败的相关性与回送事件。

> 修订：本 ADR 的事件—效果边界与 Port 隔离决策保持有效。commit `4fedfaa`（2026-08-19）移除了 `arm`/`disarm` 门控，因此事件状态载体由“逐侧授权、故障、硬限速”更新为“逐侧运动使能、故障、硬限速”（`motion_enabled` 为只读派生值，不再有可写的 `armed`）。
