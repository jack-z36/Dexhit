# 源码阶段索引

源码按主链阶段平铺；当前只保留输入输出边界，不提前创建空包或共享模块。

- [collection](collection/README.md)：采集现场数据并交付 `raw MCAP`。
- [processing](processing/README.md)：把 `raw MCAP` 处理为 `LeRobotDataset v3`。
- [training](training/README.md)：从 `LeRobotDataset v3` 训练并交付 `ACT bundle`。
- [deployment](deployment/README.md)：加载 `ACT bundle`，连接运行环境并执行策略。
