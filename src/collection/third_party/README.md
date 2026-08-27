# Collection 第三方运行时

本目录只存放未经 Dexhit 修改的第三方运行时，不存放 Collection 业务源码。根目录的 `COLCON_IGNORE` 保证 `colcon --base-paths src/collection` 不会把 vendor 安装空间识别为本仓库源码包。

当前固定依赖：

- 上游项目：Agilink OmniHand SDK；
- 上游 commit：`026740d9fdd8ba32b0605fa702a992b322076f1b`；
- SDK 版本：1.1.8；
- 平台：Linux x64、ROS 2 Jazzy；
- 安装前缀：`agillink_omnihand_sdk/linux/x64/ros2/jazzy/`。

约束：

- 不在 vendor 前缀中加入 Dexhit 源码、测试或补丁；
- 不从生产源码通过相对文件路径导入 vendor 内容；运行时只通过 SDK 的 setup/ament 前缀发现；
- 不把 aarch64 二进制复制到当前 x64 工作站目录；
- 升级 SDK 时必须同步更新本说明、逐文件来源核验和架构门禁。
