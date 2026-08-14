---
status: accepted
---

# O10 无动作主动关节读取使用逐侧 Service

O10HardwarePort 为左右手分别提供 `/o10/{side}/read_active_joints` 的 `ReadO10ActiveJoints` Service。请求为空且手侧由 Service 名称确定；Provider 必须在请求到达后执行一次不会改变手姿态的新读取，成功响应携带采样时间和有限、合法的固定 10 维主动关节位置，不能返回历史 Topic 缓存。生产厂商 Provider 与无真机纯软件 Provider 实现同一 ROS wire contract；控制客户端拥有超时和响应复核，启动初始化与清除锁存故障都使用该接口。选择 Service 是为了获得逐请求相关性和明确完成结果，同时保留既有最终命令、反馈和错误轮询 Topic。
