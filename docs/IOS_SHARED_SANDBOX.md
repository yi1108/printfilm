# 正式服务内的 iOS 沙箱测试

本方案不增加服务、数据库、Redis 或域名。正式 Apple 环境与统一钱包环境均保持 `Production`；沙箱使用新增的 `marketplace_sandbox_*` 测试账本，不写 `users.balance_fen/frozen_fen` 或正式资金流水。

## 后台操作

1. 发布代码并重启 API。新增四张测试表及充值订单的可空 `payment_environment` 列沿用启动自动增量迁移及统一数据库锁，不搬迁历史资金；旧订单不回填。新沙箱充值订单标记 Sandbox，排除正式充值列表与收入统计，单笔订单查询仍返回测试环境。
2. 在“系统设置 → 支付计费 → Apple 支付接入”保持交易环境 `Production`，补齐原有 Bundle ID、Apple App ID、密钥、根证书和商品配置。
3. 填写“沙箱测试用户 ID”，例如 `123,456`，使用平台用户编号，不是邮箱或 Apple 沙箱账号。开启“允许白名单账号沙箱新购”并保存。该开关独立于普通用户的“允许 Apple 新购”。
4. App Store Connect 的生产与 Sandbox 服务器通知均可使用同一个公网 HTTPS 地址：`/api/billing/apple/notifications`。Apple 官方验证器分别验证两种环境；后端不会相信客户端自报的环境。
5. 测试设备使用 Apple Sandbox / TestFlight 交易。加入平台白名单不会让 StoreKit 自动切成沙箱；购买前必须核对客户端交易环境。真实 Production 付款仍入正式账本。
6. 在现有数字资产市场运营页选择 `Sandbox`，查看测试充值、钱包、流水、来源和解锁订单。测试交易不允许进入财务对账、收入补估或真实打款。

关闭沙箱新购只暂停新的充值意向和测试解锁，保留验单、通知、补偿、退款、退款撤销及已有权益播放。保留密钥、根证书和测试用户白名单。移出白名单后，该账号 App 恢复正式钱包视图，已有测试记录保留，不合并余额。

系统配置沿用现有缓存机制。多 API 实例发布时请更新并重启全部实例，再核对后台配置。

## iOS 接口约定

仍使用原有域名、登录和接口，无需传环境切换参数或新增请求头：

1. 登录后携带 Bearer Token 请求 `GET /api/billing/skus?channel=apple_iap` 或 `GET /api/marketplace/app/v1/coin-products`。白名单账号返回 `environment=Sandbox`；游客和普通账号返回正式环境。按 `purchasing_enabled` 控制入口。
2. `POST /api/billing/orders`，请求仍为 `{"sku_id":"topup_10","pay_type":"apple_iap","idempotency_key":"唯一购买编号"}`。也兼容 `/api/marketplace/app/v1/iap/apple/purchase-intents`。
3. 按响应的商品编号和 `app_account_token` 发起 StoreKit 购买，核对 StoreKit 交易环境与本次意向环境一致。
4. `POST /api/billing/apple/transactions/verify` 提交原始签名交易及 `intent_id`。服务端官方验签、对应环境权威查询、账号归属校验成功并提交后，才可 `finish()`。重复提交不会重复加分。
5. **App 使用 `GET /api/marketplace/app/v1/me/wallet` 刷新余额**。白名单账号示例：

```json
{
  "environment": "Sandbox",
  "wallet_type": "sandbox_test",
  "test_only": true,
  "balance_fen": 10000,
  "balance_coins": 10000,
  "frozen_fen": 0,
  "debt_fen": 0,
  "spendable_fen": 10000
}
```

客户端应显示“沙箱测试积分 / Sandbox test points”，不要将其当作真实可消费余额。兼容已上线 iOS：无参数的 `GET /api/billing/wallet` 也按账号白名单返回相同测试余额，保留 `balance_fen`、`frozen_fen`、`balance_yuan`、`frozen_yuan` 等原字段，所有单位字段来自同一账本，旧版 iOS 无需增加参数。Web 已改用 `GET /api/billing/wallet?view=production` 显式读取正式余额。普通用户的无参数请求仍返回正式余额。该参数只选择本人钱包视图，不改变 AI 扣费、资金环境或账号归属。旧版 iOS 若不识别 `test_only`，不会自动出现测试标识，应只用专门测试账号验证。

加入或移出白名单后，客户端应重新拉取 capabilities、钱包、已购及解锁状态；发现返回环境改变时清除上一环境的钱包与权益缓存，重新创建播放会话，不在本地合并两套余额。

6. `/me/wallet/entries`、`/me/unlock-orders`、`/me/entitlements` 及详情/播放按服务端账号环境读取。测试解锁仍调用 `POST /api/marketplace/app/v1/unlocks`，请求字段不变。
7. 沙箱权益只生成 `Sandbox` 授予，不写生产 `Entitlement`，不产生创作者收益。免费与试看规则不变。移出白名单后不能继续用测试权益播放正式付费内容。

白名单账号 Web 充值和 AI 冻结/结算始终使用正式钱包；沙箱积分不能支付真实 AI 成本。测试视频仍使用实际媒体服务，OSS 播放资源本身并非模拟。

## 退款与历史数据

- 每笔 Sandbox 充值保留独立来源，退款扣回未用测试积分。
- 用该来源解锁的视频撤销该次测试权益，混合使用的其他有效测试来源返还；不形成正式欠费。
- 退款撤销恢复应有测试积分，不恢复已撤销的视频权益；用户可以重新解锁。旧退款不会撤销后来新购的授予。
- 关闭新购或移出白名单后，已存在的意向/交易仍可补验单及处理退款。
- 旧版曾写入统一钱包或旧观影币表的 Sandbox 记录不会自动迁入新账本。缺少新账本来源时返回 `SANDBOX_LEGACY_REVIEW_REQUIRED`，需专项核对，禁止猜测补账或转成正式积分。

## 联调清单

核对正式余额在沙箱充值、解锁、退款前后不变；正式 AI 仍可用真实积分生成。覆盖重复验单、跨账号拒绝、通知先到、杀 App 补单、停新购后的补单与退款、混合批次撤权、退款撤销和重新购买。代码测试使用网络替身，真实 Apple Sandbox / TestFlight、公开通知可达性和真机播放仍须实测。
