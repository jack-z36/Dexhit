# 修复方案：Launchpad 模板选择被状态同步冲掉

## 根因
模板/方块点击只改前端本地 `draft`，从未持久化到后端；后端 ~10Hz WebSocket 全量快照 + 2.5s 轮询经 `applySnapshot` 无条件用服务端旧 `config` 覆盖 `draft`，选择在 <100ms 内被回滚；随后点"启动"提交的是空/旧集合，后端对空集合校验通过并静默创建空 run（runs/launchpad 下 4 个 `*_real` 空 run 为证）。

## 修改一：前端草稿保护（web/src/App.vue）

引入"本地未保存编辑"标记，快照不再无条件回灌 draft：

1. 新增 `draftDirty` 标志与 `syncDraftFromServer(config)`（把现 applySnapshot 第 39-40 行的合并逻辑移入，并清脏标记）。
2. `applySnapshot` 改为：首次加载（页面打开第一帧）或 `draftDirty === false` 时才从 `snapshot.config` 同步 draft；存在本地未保存编辑时跳过同步，只更新 `state`（nodes/run/validation/events 显示不变）。
3. 所有本地编辑路径置脏：`chooseTemplate`、`toggleBlock`（非运行分支）、以及侧别/参数档案/UDP 端口/Actor/CAN 通道/label 六个表单项（加 `@change` 置脏）。
4. `saveConfig` 成功后显式调用 `syncDraftFromServer(result.config)`（不能依赖 applySnapshot，因为此刻是脏的），持久化成功即恢复"服务端权威"。
5. 运行中语义修正：网格选中态（`selected` class 与 `aria-pressed`）在 `running === true` 时改由服务端 `nodes[id].expected` 派生（新增 `desiredBlocks` computed），非运行时仍读 `draft.blocks`——消除运行中单节点启停后 draft 与实际期望的错位；运行→停止转换后由第 2 条的干净同步自然回种 draft。

## 修改二：后端两处加固（rokoko_omnihand_launchpad/orchestrator.py）

1. `snapshot()`（约 509 行）：`validate_blocks(self._config["blocks"])` 改为带上 configure 时保存的 confirmation 状态（configure 写 config 时增加 `"confirmed": bool(payload.get("confirmation"))`），消除"已确认保存的危险组合在快照中永远报硬阻止"。
2. `start_all()`（约 485 行）：空方块集合直接 `raise ValueError("no blocks selected — 点亮至少一个方块")` → 409，杜绝"成功启动空会话"。

## 修改三：重建前端产物

后端伺服的是 `web/dist`（start_launchpad.sh 从源码树运行），改完 App.vue 后执行 `npm run build` 重新生成 dist。

## 测试

后端 pytest（在现有 `test/` 接缝测试中追加，走 HTTP API）：
- 空集合 `POST /api/start` → 409 且错误信息明确；
- 带 confirmation=true 保存 `synthetic_input+hcan_provider` 后 `GET /api/state` 的 `validation.valid === true`；
- 既有测试全量回归。

前端无测试基建，用浏览器黑盒验证（见下）。

## 验证流程（实现完成后执行）

1. 重启 launchpad 服务，浏览器打开控制面。
2. 点"真机"→ 4 个业务方块保持点亮 ≥5s（跨过 WS 帧与 2.5s 轮询两个冲掉窗口）；改侧别/label 同样粘住。
3. 点"启动选中方块"→ 用 `GET /api/state` 或新 run 的 events/metadata 确认 `blocks` 为 4 个方块（对照修复前的 `blocks: []`）；若本机无 HCAN 硬件则应得到明确的 preflight 拒绝提示（这是设计行为，同样是修复目标——用户能看到原因而不是无声失败）；随后全停。
4. "数据链路"模板与手动增删方块路径同样验证一遍；危险组合流程（合成输入+真机）仍正常弹二次确认。
5. 在 DOCS/03_工程/launchpad/issues/03 ticket 文件追加本次修复记录。

## 范围外（明确不做）

- run 目录创建时机从 configure 移到 start 的重构（会动现有测试约定，另行立项）；
- `install/` 下陈旧前端副本清理；
- 前端单测基建（vitest）引入；
- runs/launchpad 下 4 个空 `_real` run 的删除（用户自行决定）。