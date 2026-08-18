# ADR-0011：Launchpad 真机与 system_test 编排边界

- 状态：Accepted
- 日期：2026-08-18
- 范围：`rokoko_omnihand_launchpad`、生产 composition、`rokoko_omnihand_system_test`

## 背景

Launchpad 需要同时支持真机、数据链路和全链路 mock/sim。`system_test` 中的纯软件
Provider 和场景生成器对无硬件回归有价值，但它们不是生产硬件依赖。若把测试包作为
真机 composition 的普通依赖，真机启动就可能加载测试代码或错误地选择软件 Provider。

## 决策

1. 真机模式的编排配置 MUST NOT 引用、加载或启动
   `rokoko_omnihand_system_test`，也不得通过默认值或间接 launch 引入它。
2. mock/sim 模式可以显式引用 `rokoko_omnihand_system_test` 的纯软件 Provider 和
   场景生成器；该引用必须由模式选择清楚标记，不能成为生产 composition 的隐式依赖。
3. `rokoko_omnihand_system_test` 不得反向依赖 Launchpad，也不得接触厂商 SDK、CAN、
   USB 或设备文件。
4. 架构门禁继续把生产包到 `system_test` 的 manifest/import 边视为阻断错误；模式化
   mock 引用由 Launchpad 的编排测试在对应 ticket 中验证。

## 后果

- 真机安全边界可由 manifest、composition 和源码门禁共同检查，而不依赖操作者记忆。
- mock 模式仍可复用现有确定性测试资产，不复制第二套 Provider 或 JSON 场景生成器。
- Launchpad 后续实现必须把模式选择保持在最外层 adapter；不能为了复用代码把测试包
  提升为生产业务包依赖。

## 未决事项

具体 mock 模式的 HTTP 配置和替身进程协议由后续 Launchpad tickets 定义；本 ADR 只
固定真机与测试代码的依赖边界。
