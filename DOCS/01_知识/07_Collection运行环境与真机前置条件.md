# Collection 运行环境与真机前置条件

本文记录 Collection 阶段（尤其是 Rokoko → OmniHand O10 Launchpad）运行时需要的本机基础环境和设备前置条件。它是相对稳定的环境知识；某一次会话是否已启动、USB 是否枚举、故障是否清除，仍以 `DOCS/03_工程/` 中的当前状态和现场观测为准。

## Python 数值环境

项目自有的 Python 运行时环境固定使用：

```text
/home/hit/miniforge3/envs/dexhit_collection
```

典型使用方式：

```bash
source /home/hit/miniforge3/etc/profile.d/conda.sh
conda activate /home/hit/miniforge3/envs/dexhit_collection
```

该环境用于项目自有的 Python/ROS 节点及数值 Adapter，至少应能提供：

- Python 3.12；
- Pinocchio：O10 URDF 运动学与 Jacobian；
- NLopt：Phase 1 单指 SLSQP；
- NumPy：数值输入、输出和离线验证。

在当前工作站已观测到 Python 3.12.13、Pinocchio 4.1.0、NLopt 2.11.0 和 NumPy 2.5.1。启动前应在目标环境内重新执行 import 检查；不要用缺少数值依赖的系统 Python 替代该环境。

ROS 进程还需要先加载 ROS 发行版环境，例如：

```bash
source /opt/ros/jazzy/setup.bash
```

若使用工作区临时构建/安装空间，还必须继续 source 对应的 `install/setup.bash`。Python 环境和 ROS 安装空间是两个独立边界，二者都生效才算运行环境就绪。

## Launchpad 控制面

`rokoko_omnihand_launchpad` 是 Collection 下的本机设备编排层，控制面默认监听：

```text
http://127.0.0.1:8710
```

Launchpad 运行前应满足：

- 使用上面的 `dexhit_collection` Python 环境；
- ROS Jazzy 环境已 source；
- 真机模式所需 ROS 包、参数档案和厂商节点已进入当前 ROS 安装空间；
- 真机模式的数值依赖、设备枚举和参数预检全部通过。

Launchpad 网页不提供 `arm`、`disarm`、`clear_fault`。真机授权必须由操作者在终端显式完成；网页启动成功、ROS topic 有发布者或反馈可读，都不能单独证明实体灵巧手已经安全运动。

## OmniHand O10 设备前置条件

当前用户已确认：OmniHand 灵巧手已经与上位机连接。该信息只表示现场连接前提已具备；每次真机启动仍需重新观察：

1. USB-CANFD 设备身份、权限和 CAN 通道是否正确枚举；
2. 左右侧 Provider 是否连接到预期实体设备；
3. 反馈是否新鲜、关节值是否有限且在合法范围；
4. `fault_latched` 是否为 false、控制状态是否允许进入下一阶段；
5. 在显式 arm 前，是否没有任何会驱动实体手的命令发送。

项目已知的 HCAN 设备识别条件为 USB VID:PID `a8fa:8598`；这只是 Launchpad 的设备预检条件，不是对当前设备枚举结果的永久断言。断开、身份不匹配、反馈不新鲜或故障锁存均属于停止条件。

## 验证入口

环境验证应从低风险到高风险逐级进行：

```bash
/home/hit/miniforge3/envs/dexhit_collection/bin/python -c \
  'import pinocchio, nlopt, numpy; print("numeric runtime ok")'
source /opt/ros/jazzy/setup.bash
ros2 pkg list | rg 'rokoko|omnihand|hand_retargeting'
lsusb
```

随后才运行 Launchpad 的 preflight、数据链路或 sim 验证。真机验收还需要独立的会话目录、MCAP、`/rosout`、事件时间线和系统监控证据；这些证据不能由软件单元测试替代。

## 当前工作站实测备注

2026-08-18 在当前工作树检查到目标环境和 Pinocchio/NLopt/NumPy 可 import。直接用该环境解释器检查 Launchpad 辅助依赖时，发现 `uvicorn` 的 `click` 以及 ROS Python 侧的 `yaml` 不在该解释器可见路径中；这应在启动前通过正确的环境激活、ROS setup 或依赖安装复核。该备注不改变项目约定的环境路径，也不把一次未完成的启动检查写成真机验收通过。
