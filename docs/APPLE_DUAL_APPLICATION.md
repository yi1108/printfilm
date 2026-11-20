# 国内与国际 iOS 应用支付

后台「支付与通知 → Apple 支付接入」维护两款应用：

- 国际版继续使用原 `apple_bundle_id`、`apple_app_id`，不覆盖已上线配置。
- 国内版新增 `apple_domestic_bundle_id`、`apple_domestic_app_id`，不填写时保持旧版行为。App ID 是 App Store Connect 的数字 Apple ID。
- 两款应用共用现有 Issuer ID、Key ID、私钥和根证书，因此要求同一个 Apple 开发者账号，并授权服务器凭证访问两款应用。不同开发者账号的独立凭证不在本次支持范围。

两款应用在各自 App Store Connect 中创建各自 Product ID 的消耗型商品，各自登记后绑定同一套积分套餐；登记商品不代表 Apple 已审核可售。每款应用分别配置生产及沙箱 Notifications V2，地址仍为 `/api/billing/apple/notifications`。

旧国际版继续调用现有接口，无需改动。国内版查询套餐需要增加 app_edition=domestic；验单无需自行声明应用身份。服务端对后台登记的两个应用分别执行官方签名验证，只有通过验证的 Bundle ID 才用于后续权威交易查询、退款和消费信息回传。未登记包名不接受。应用身份随原始 Apple 凭证保留，不修改历史交易。

通知历史补偿为两款应用维护独立游标；国际版保留原有游标，国内版使用 `cn:Production`、`cn:Sandbox`。投入使用后不要将国内版字段替换为另一款应用，避免复用原补偿进度；若新增第三款应用需扩展独立应用登记。

两款应用共用账号、稳定 appAccountToken、充值额度和正式钱包。Production / Sandbox 是交易环境，国内 / 国际是应用身份，两者独立；既有沙箱白名单和测试资金隔离不变。不得为接入国内包切换正式钱包环境。

部署无需重新迁移余额，配置保存在现有系统设置中。上线前分别使用两款应用完成 Sandbox / TestFlight 的购买、重复验单、杀进程补单、通知、退款测试，确认原国际版仍正常。分享唤醒所需的双 App AASA 配置不属于本次支付修改。


## 独立商品与后台配置

后台支付配置按「国际版应用」「国内版应用」「公共服务器连接」分组，商品区提供国内/国际切换。商品必须单独登记，默认停用；每个应用的同一套餐最多启用一个商品。历史商品及所属应用不可改写，旧记录自动补齐 app_edition=international，不重算余额。

国内四档预置：
- topup_10 → com.qianzhi.deep.app01.credits.topup_10（10,000 积分）
- topup_49 → com.qianzhi.deep.app01.credits.topup_49（49,000 积分）
- topup_99 → com.qianzhi.deep.app01.credits.topup_99（104,000 积分）
- topup_199 → com.qianzhi.deep.app01.credits.topup_199（220,000 积分）

客户端示例：
- GET /api/billing/skus?channel=apple_iap&app_edition=domestic
- GET /api/marketplace/app/v1/coin-products?app_edition=domestic
- POST /api/billing/orders 请求体增加 "app_edition": "domestic"，其他套餐、幂等键字段不变。
- POST /api/marketplace/app/v1/iap/apple/purchase-intents 继续传查询得到的国内 product_id 和 idempotency_key。
- POST /api/billing/apple/transactions/verify 继续提交 signed_transaction_info；服务端校验签名 Bundle ID 与已登记商品所属应用一致，防止串用。

app_edition 只负责购买前选择商品，不能证明付款，也不改变钱包或沙箱白名单。漏传默认 international，以兼容已上线国际版；国内版必须接入该参数，不能期待在付款前从 Apple 回执识别版本。

新增 app_edition 列沿用 API 启动增量迁移和统一数据库锁，不需要再次迁移积分；不要手工将历史国际版商品改归国内版。登记并启用前请核对对应 App Store Connect 的商品审核与售价。


## 请求头兼容

购买前选择商品同时支持查询参数 app_edition 或 X-App-Edition 请求头；也可以通过已在后台登记的 X-App-Bundle-ID 推断版本。国内版示例：

GET /api/billing/skus?channel=apple_iap
X-App-Edition: domestic
X-App-Bundle-ID: com.qianzhi.deep.app01

包名必须与后台国内版 Bundle ID 完全一致。显式参数、请求头与包名如同时提供，必须相互一致，否则返回 409；未知版本返回 422，未登记包名返回 409。不再静默回落另一版本。完全未提供这些信息时仍默认国际版。

/coin-products 与 /api/billing/orders 同样识别这些请求头；订单 body 中显式 app_edition 也参与一致性校验。App 购买意向通过已登记商品推断应用，若提供请求头则同时校验。验单仍只信任 Apple 签名，不信任请求头。国内版新购检查使用国内版的 Apple 验签配置。

purchasing_enabled=false 仍可能由钱包未启用、Apple 新购关闭、凭证/根证书/SDK/应用 ID 缺失、环境不匹配或沙箱白名单限制造成，版本选择正确不代表支付配置已就绪。
