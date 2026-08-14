# Rokoko 原始手部帧 ROS 接口契约

本文固定 Phase 1 中 Rokoko 接收节点到手部重定向节点的跨节点数据语义。消息文件、Topic 和 QoS 的实现必须服从本文；本文不定义 UDP socket 参数、JSON 解析代码或重定向算法内部结构。

## 消息与 Topic

项目自定义消息包和消息为：

```text
rokoko_omnihand_msgs/msg/RawHandFrame
```

左右手使用独立 Topic：

```text
/rokoko/left/raw_hand
/rokoko/right/raw_hand
```

逻辑手侧由 Topic 身份确定，消息不重复携带 `side` 字段。左右手允许独立存在、独立失败和独立 stale。

消息字段固定为：

```ros
std_msgs/Header header
uint32 actor_index
string actor_name
float64 source_timestamp
string[21] node_names
geometry_msgs/Point[21] positions
geometry_msgs/Quaternion[21] orientations
```

## 时间与坐标语义

`header.stamp` 是接收节点在本机收到 UDP 数据包时获取的 ROS 接收时间，不是 JSON 解析完成时间、发布时刻或 Rokoko 源时间。双手来自同一个场景包时共享同一 `header.stamp`。它用于 stale、软平滑、端到端年龄和 MCAP 对齐。

`header.frame_id` 固定记录原始坐标约定：

```text
rokoko_world_y_up_z_forward
```

该字符串是数据语义标签，不要求存在对应 TF frame。若真实数据证明官方坐标约定与此不同，必须显式修订契约，不能静默转换后继续使用旧标签。

`source_timestamp` 原样保存 JSON v3 的场景级 `scene.timestamp`。官方 Custom Streaming v3 schema 将该字段列为场景成员；接收节点要求它存在且为有限数值，缺失时整包无效。在目标现场真实数据确认其单位和 epoch 前，不得把它转换为 ROS 时间或与 `header.stamp` 相减；当前算法只把它视为可录制的原始数值。

## Actor 语义

`actor_index` 是接收节点配置选中的 Rokoko Actor 数组索引，Phase 1 默认值为 0，一次只处理一个 Actor。索引不存在时整包不产生手部消息。

`actor_name` 原样保存该 Actor 的名称，只用于记录和诊断，不参与路由或控制。其是否允许空字符串由正式 JSON v3 样例和真实数据验证后固定，不能由实现者猜测。

## 21 节点规范顺序

`node_names[i]`、`positions[i]` 和 `orientations[i]` 在同一索引 `i` 表达同一个节点。接收节点必须依据 JSON 节点名称重排，不能假设源数组已经按规范顺序排列。

语义顺序固定为：

| 索引 | 节点语义 |
| ---: | --- |
| 0 | Hand |
| 1–4 | Thumb Proximal、Medial、Distal、Tip |
| 5–8 | Index Proximal、Medial、Distal、Tip |
| 9–12 | Middle Proximal、Medial、Distal、Tip |
| 13–16 | Ring Proximal、Medial、Distal、Tip |
| 17–20 | Little Proximal、Medial、Distal、Tip |

具体 `node_names` 使用 Rokoko 官方 Custom Streaming 示例中的字段拼写：逻辑侧前缀 `left`/`right` 加上表中 PascalCase 语义，例如 `leftHand`、`leftThumbProximal` 和 `rightLittleTip`。接收节点拥有该唯一规范表；重定向节点必须验证收到的 21 个名称与规范表完全一致，不能只按数组索引盲用。目标现场真实抓包仍需作为兼容性回归证据，若与官方示例不一致必须显式修订契约。

## 原始数值处理

`positions` 保留 Rokoko 世界坐标数值，不做单位换算、掌心相对化、镜像、滤波或尺度归一化。

`orientations` 以 ROS `Quaternion` 的 `x,y,z,w` 字段保存源四元数。四个分量必须有限，范数不得接近零；接收节点不归一化非单位四元数。四元数不参与当前归一化与 IK，但为录制、诊断和未来扩展保留。

每侧只有完整、名称唯一、数值有限且四元数合法的 21 节点才能发布。缺失侧不补零、不复制另一侧，也不复用历史侧帧。

## 分包与失败语义

| JSON v3 场景结果 | 发布行为 |
| --- | --- |
| JSON 无法解析或场景级字段非法 | 左右均不发布 |
| 只有合法左手 | 只发布左 Topic |
| 只有合法右手 | 只发布右 Topic |
| 双手均合法 | 左右各发布一条，共享场景接收时间和源时间 |
| 一侧非法、另一侧合法 | 只发布合法侧 |
| Actor 索引不存在 | 左右均不发布 |

坏包或坏侧不得终止接收进程。实现发布节流日志和可观测计数器；具体诊断字段留待实现 spec 固定。

## QoS

Rokoko 接收节点发布左右 Raw Topic 时固定提供：

```text
reliability = reliable
durability  = volatile
history     = keep_last
depth       = 10
```

`depth=10` 是可配置的接口默认值，用于吸收短时传输抖动；它不承诺在进程阻塞、网络故障或录制器过慢时绝不丢帧。

手部重定向节点订阅左右 Raw Topic 时固定请求：

```text
reliability = best_effort
durability  = volatile
history     = keep_last
depth       = 1
```

因此重定向回调来不及消费时只保留最新待处理帧，不累积旧动作队列。Phase 1 的正常运行前提仍是操作者把 Rokoko 发布频率配置为低于 IK 可持续吞吐；深度 1 只是违反该前提时限制时延扩散的防御行为，不引入独立调度模块。

外部 rosbag2/MCAP 录制器对 Raw Topic 请求 `reliable + volatile`，以利用发布者提供的可靠传输；这只覆盖 ROS/DDS 层，不保证 Rokoko 上游 UDP、进程存活或磁盘写入永不丢失。

QoS 的 `deadline` 与 `lifespan` 使用默认值，不参与控制安全判定。stale 仍由应用层依据 `RawHandFrame.header.stamp`、本机接收时间和配置阈值判断；QoS 事件只能作为诊断证据。

## 录制边界

两个 Raw Topic 必须可由外部 rosbag2/MCAP 录制。Rokoko 接收节点本身不拥有 MCAP 文件写入职责。

下游重定向到 O10 控制入口的 `JointState` 目标契约见《OmniHand O10 控制契约与模块边界》中的“重定向软目标与厂商命令语义”。
