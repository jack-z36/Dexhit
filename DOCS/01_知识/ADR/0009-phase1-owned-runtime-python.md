---
status: accepted
---

# Phase 1 自有运行包固定使用 Python 3

Phase 1 的 Rokoko 接收、手部重定向、O10 控制和生产硬件 Adapter 等 Dexhit 自有运行代码使用 Python 3/`ament_python`；ROSIDL 接口与无节点资产包可以使用 `ament_cmake`，厂商外部 C++ 节点不属于本决定的受管实现。该选择延续当前控制包、便于在同一套 AST/import 门禁下守住 Core/Application/Adapter 边界，并利用现有 Pinocchio/NLopt Python 接口；代价是必须先用无真机基准证明可持续 IK 吞吐。若性能证据要求迁移 C++，必须先新增或更新 ADR，并把 include、CMake link 和编译目标依赖门禁补齐后再改变语言。
