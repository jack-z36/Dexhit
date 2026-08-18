# 08 — run 历史页

**Spec:** [08_Launchpad 网页一键启动遥操作系统 Spec](../../08_Launchpad网页一键启动遥操作系统Spec.md)

**What to build:** 操作者在浏览器查看历史 run 会话：列表呈现时间、模板名或 custom、label、磁盘占用与包含的产物（mcap/metadata/events/sysmon/日志）；支持手动删除单个 run 目录。启动配置页可填写 label 并体现在 run 目录名中。无自动清理，删除是显式动作且带确认。

**Blocked by:** 03 — 前端方块网格页；07 — 录制全家桶与 run 会话。

**Status:** ready-for-agent

- [ ] run 列表正确显示时间、模板/custom、label、大小与产物清单
- [ ] 手动删除单个 run 带确认且生效
- [ ] 启动时填写的 label 体现在 run 目录名
- [ ] 页面数据与 runs/launchpad/ 目录实际内容一致
