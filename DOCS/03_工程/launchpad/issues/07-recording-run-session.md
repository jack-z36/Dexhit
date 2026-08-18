# 07 — 录制全家桶与 run 会话

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 每次启动自动创建 run 会话目录（runs/launchpad/ 下时间戳_模板名或custom[_label]）：节点日志（各进程 stdout 落盘）、metadata（方块清单、起始模板、参数快照、git commit、USB 设备、模式与侧别）、events.jsonl（网页时间标记 + 方块中途启停事件）总是留存。点亮录制器方块（或运行中点亮）后，ros2 bag 以 mcap 存储启动外部录制进程，覆盖全部公开 topic（两侧 raw_hand、retargeting state、command、O10ControlState、joint_cmd、joint_states、joint_error_states）与 /rosout，外加 1Hz CPU/内存采样的 sysmon 文件；熄灭录制器方块即停录且记入 events。数据链路模式下验证可录 topic 子集的完整性，全 topic 集在 12 号验收票的真机环境验证。录制进程同样是编排器子进程，遵循 PDEATHSIG 语义。

**Blocked by:** 05 — 真节点接入：数据链路模式与 preflight 迁移。

**Status:** ready-for-agent

- [ ] 每次启动创建 run 目录，含节点日志、metadata（方块清单/起始模板/参数快照/git commit/USB/模式侧别）、events.jsonl
- [ ] 点亮录制器方块启动 mcap 录制，数据链路模式下可录 topic 子集全部落盘
- [ ] /rosout 被录制，节点 warning/error 可从 bag 中检索
- [ ] sysmon.jsonl 以 1Hz 记录 CPU/内存
- [ ] 停录后 bag 完整可读（metadata.yaml 存在、mcap 非空、storage 为 mcap）
- [ ] 开录/停录事件与网页打标写入 events.jsonl
- [ ] 录制进程为编排器子进程，kill -9 编排器时跟随退出
