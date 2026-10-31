# example.hello

仅用于验证 Iris 官方插件仓库端到端流程的示例插件，不提供实际业务能力。

- id：`example.hello`
- 版本：`1.0.0`
- 提供：`admin.ui`（一个静态设置页）
- 申请宿主能力：`logger`

设置页是 `ui/index.html`，没有配置项；`admin.request` 的 `status` 接口只返回一条问候，供握手测试使用。
