# iOS / Web 统一余额充值接入

平台余额单位为人民币分额度。`coins` 是兼容别名，1 币 = 1 分额度；USD 是付款币种，不是余额币种。充值不产生创作者收益，余额消费时才按实际资金来源分摊。

## 商品与价格

### 后台 Apple 支付接入

入口为“系统设置 → 支付计费 → Apple 支付接入”。配置 Bundle ID、数字 Apple App ID、Issuer ID、Key ID，上传内购服务器 API 的 .p8 私钥，以及从 Apple PKI 下载的根 CA 证书（支持多选 DER/CER/PEM）。点击该分区“保存 Apple 接入配置”独立保存，私钥复用系统密钥加密机制，读取接口只返回是否已配置，不返回私钥。

“检查已保存配置”检查必填项、私钥及根证书格式、服务器 SDK，显示通知处理状态，不调用真实支付，也不证明商品可售或密钥权限正确。配置完整后运行时读取数据库配置，并启动通知处理；无需编辑 .env。多 API 进程部署沿用现有系统设置缓存机制，发布/重启全部实例后应再次核对配置，避免其他进程仍使用旧缓存。

交易环境可在后台选择 Production 或 Sandbox，保存后用于验单与通知处理。切换不迁移已有余额、资金来源、订单或权益，账户环境不匹配仍会被拒绝；请使用对应环境的测试账户。已有生产交易的服务应保留在生产环境处理付款及退款，Sandbox 使用独立测试部署、数据库和 Redis。通知地址从“站点工具”的公网 HTTPS 后端基址生成，将其配置到 App Store Connect 的 App Store Server Notifications V2 对应环境中。新购开关不控制已付款履约和退款处理；关闭新购时请保留有效密钥和证书。

四档商品映射在下方“Apple 内购商品配置”逐档登记。启用新购前仍须完成统一余额核对、Apple 商品配置及真实 Sandbox/TestFlight 验收。美元财务汇率继续在运营后台维护。

- `topup_10` / `com.deep.printfilm.credits.topup_10`：CNY 10000 分，USD 1499 美分，到账 10000 分额度。
- `topup_49` / `com.deep.printfilm.credits.topup_49`：CNY 49000 分，USD 6999 美分，到账 49000 分额度。
- `topup_99` / `com.deep.printfilm.credits.topup_99`：CNY 99000 分，USD 13999 美分，到账 104000 分额度。
- `topup_199` / `com.deep.printfilm.credits.topup_199`：CNY 199000 分，USD 27999 美分，到账 220000 分额度。

人民币和美元均为固定零售价。美元财务汇率只决定收入核算，不决定商品价格、到账或赠额。Stripe 同一套餐采用上述美元档位，其余币种及非套餐报价保留原逻辑。已有订单价格不会随新配置变化。

## 接口顺序

所有接口使用 HTTPS；登录接口复用现有账号，Bearer Token 放在 Keychain。语言使用 `Accept-Language: zh-CN` 或 `en-US`。禁止在日志中输出 Token、JWS、Apple 密钥。

1. `GET /api/billing/skus?channel=apple_iap`。检查 `purchasing_enabled`，获取 `skus`。每项包含 `id`、`product_id`、`amount_fen`（人民币基准）、`credit_fen`、`bonus_fen`、`credit_currency=CNY` 和 `expected_prices`（CNY/USD 整数最小单位）。商品未配置时不伪造可购商品。
2. 向 StoreKit 请求这些 Product ID。仅展示真实存在的消耗型商品；币种须为 CNY/USD，`Product.price * 100` 必须等于对应预期价格。展示 `Product.displayPrice`；额度另标“人民币平台额度 / CNY platform credit”。价格不匹配时禁用该档购买，提示刷新或稍后重试。后台保存映射不等于 Apple 商品已经审核可售。
3. 登录后 `POST /api/billing/orders`，提交 `{"sku_id":"topup_10","pay_type":"apple_iap","idempotency_key":"UUID"}`。响应含 `intent_id`、`order_id`、`out_trade_no`、`product_id`、`app_account_token`、`credit_fen`、`expected_prices`。同一次购买请求必须持久保存并复用幂等键，创建意向失败不能重新生成键盲目购买。新一次用户确认购买使用新键。
4. `product.purchase(options: [.appAccountToken(token)])`。再次比较意向价格和 StoreKit 价格。取消不显示成功，`.pending` 提示等待 Apple 批准。
5. 将 StoreKit 原始 `jwsRepresentation` 提交到 `POST /api/billing/apple/transactions/verify`，请求 `{"signed_transaction_info":"<JWS>","intent_id":123}`。未完成交易恢复可以省略 `intent_id`，账号归属仍由服务端稳定 Token 验证。不能由客户端提交价格、到账额度或用户编号。
6. 仅当服务端返回 `finish_transaction=true` 时 `transaction.finish()`；`credited=false` 表示退款终态，不能显示充值成功。随后刷新 `GET /api/billing/wallet`，展示 `balance_fen`、`frozen_fen`、`debt_fen`、`spendable_fen`，不要自行给界面余额加数。

旧 `/api/marketplace/app/v1/coin-products`、`/iap/apple/purchase-intents` 和验单地址继续兼容。余额充值不依赖市场发现开关。生产新购仍要求统一钱包已启用、账户来源已核对及 Apple 配置齐备。

## 断网、恢复与多设备

启动后立即监听 `Transaction.updates`；登录完成及网络恢复、App 回到前台时遍历 `Transaction.unfinished`。将交易交给同一个串行履约函数，同一交易不要同时发起多个验单。

服务端按 `environment + transaction_id` 去重。服务端已到账但响应丢失时重验原交易，不能重新购买。验单失败暂不 `finish()`，保留交易供重试；401 时刷新登录状态，账号不匹配时要求登录原购买账号。退出账号应停止主动重试，不能把旧交易改绑新账号。

消耗型商品不能依赖“恢复购买”重新建立余额；余额和充值历史以 PrintFilm 服务端账号为准。Swift 示例见 [StoreKitRecharge.swift](examples/StoreKitRecharge.swift)，网络、持久幂等键和 Keychain 适配由 iOS 工程实现。

## 外币核算与后台

Apple 交易保存原币种、`payment_amount_minor`、原始毫单位金额、商店地区、人民币实收核算值及汇率快照。`amount_fen` 始终是人民币核算金额。`valuation_status=pending` 时该值为待核算占位零，不能作为免费充值或最终收入。

后台“系统设置 → 支付计费 → Apple 内购商品配置”可登记四档商品、查看固定售价与赠额，并逐档开启或停止新购；每档独立保存。商品配置位于支付计费页面下方。与“数字资产平台运营 → 苹果充值商品”共用记录。管理员核实 Apple 配置后启用。旧商品缺 USD 价格映射时，编辑保存可补齐已确认的共同套餐价；已有非空快照不覆盖。在本系统登记不会自动在 App Store Connect 创建或审核商品。

“苹果交易 → 美元实收核算”提供：

- `GET/POST /api/admin/marketplace/app/exchange-rates`：追加 USD/CNY 会计汇率版本，包含来源及账期。新交易使用最新版本，交易保存版本快照。
- `POST /api/admin/marketplace/app/transactions/{id}/valuation`，提交 `{"rate_id":123}`：补齐待核算交易，重复同版本操作幂等，不改变余额和消费额度。已核算交易拒绝替换版本。

缺汇率仍按商品快照到账，资金来源为 `pending_fx`，不可结算。补齐后按原额度区间累计取整更新暂定成本和未结算收益，同时追加财务修订及审计记录；原充值、退款事件不覆盖。退款前后均可核算。原币实际价差记录异常但不吞掉有效付款，财务对账须核对差异。

Apple 验单、通知、补偿在关闭新购后继续工作；Apple 手续费和税费由平台承担。Sandbox 必须使用独立部署、数据库和 Redis。

## 发布与验收

代码启动自动新增 App 和统一钱包结构，使用同一 advisory lock；不自动核对或重放历史余额。原统一钱包切换仍需按 [UNIFIED_WALLET.md](UNIFIED_WALLET.md) 核对，不能只开启开关跳过历史资金核对。

Apple 平台必须配置真实 Bundle ID、商品、付费协议、API 密钥、证书及通知 URL `/api/billing/apple/notifications`。这些操作不能由本项目代码冒充完成。

联调依次验证：四档大陆/美元实际价格、赠额、重复验单、通知先到、购买后杀 App、换机、跨账号拒绝、待批准、价差、缺汇率到账与补齐、AI 预扣与视频并发、退款/退款撤销、市场关闭后付款履约。服务端测试替身不是 Apple Sandbox/TestFlight 验收。
