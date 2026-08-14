---
status: accepted
---

# O10 在线模型使用版本锁定的最小资产包

Phase 1 正式运行不得依赖外部源码仓库或用户目录绝对路径。项目建立不含运行节点的专用 O10 模型 ROS 包，通过 ROS 包索引从安装空间加载。核心运行资产仅为左右生成态 URDF、左右 MJCF 和 provenance 清单；Xacro、碰撞模型、MuJoCo 场景、STL 网格及 RViz 配置不是在线 IK 的必需依赖，可在以后作为可视化扩展单独加入。

URDF 是几何、关节、掌心和 tip frame 的唯一来源。Pinocchio 加载时显式指定 `mimic=false`，保留 16 个完整运动学关节，并在启动时断言模型维数、关节名称、主动顺序、限位和所需 frame。项目不生成或维护一份手工删除 `mimic` 标签的派生 URDF，也不在运行时执行存在已知瑕疵的 Xacro。

MJCF 不作为 MuJoCo 在线模型加载，只由严格 Coupling Loader 解析 `equality/joint` 中预期的 6 条主动—被动关系。加载器验证名称映射、唯一性、五个有限 `polycoef`、左右拇指差异和耦合输出范围。URDF 与 MJCF 必须来自同一 provenance 版本。

provenance 必须记录上游仓库、固定 commit 和每个核心文件的 SHA-256；CI和启动都执行完整性及模型结构校验。模型升级必须显式更新来源、哈希与回归测试，必要时新增 ADR。

当前证据基线为 `https://github.com/manusvr/ManusOmniBridge.git` commit `f4fd0d913c2151bcb4be0d29fbc02761b9638009`。该包的 `package.xml` 声明 Apache-2.0，但上游提交没有随附许可证正文，因此技术方案可以先固定，模型文件正式复制或再分发必须等待许可确认并补齐许可证、来源和修改说明；确认前只作为外部只读开发参考。
