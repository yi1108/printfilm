# Web、iOS统一支付与平台余额

同一个PrintFilm账号只有一份可用余额和冻结余额，权威值仍为`users.balance_fen/frozen_fen`。Web易支付和iOS苹果内购只是充值渠道；到账后均可用于AI生成或视频解锁。App的`balance_coins`兼容字段等于`balance_fen`，1币=1分额度。创作者待结算收益不属于可消费余额。

## 开关与数据边界

`UNIFIED_WALLET_ENABLED=false`默认保留原AI钱包行为，禁止App资金功能回退到旧独立观影币钱包。启用前必须完成独立结构、历史来源核对及账户迁移。新注册用户在同一事务建立零余额账户标记和注册赠额来源；未核对的历史账号返回`WALLET_MIGRATION_REQUIRED`，不会猜测现金来源。

`wallet_accounts`仅标记已迁移账号，不保存第二份余额。`wallet_funding_lots/allocations/events`记录来源、消费和不可变事件；`wallet_debts/repayments`记录原欠费和逐来源偿还关系。旧`marketplace_coin_wallets/lots/entries/allocations`保留历史，只读，不再用于运行时充值或消费。

生产和Sandbox必须使用独立部署、数据库、Redis及通知地址。`MARKETPLACE_APPLE_ENVIRONMENT`决定当前部署环境；生产服务拒绝Sandbox资金，客户端不能切换钱包环境。

## API与App接入

```http
GET  /api/billing/wallet
GET  /api/billing/skus?channel=apple_iap
POST /api/billing/orders
POST /api/billing/apple/transactions/verify
POST /api/billing/apple/notifications
```

`/wallet`保留原余额、冻结、元金额、计费开关字段，增加`debt_fen`、`spendable_fen`、`pending_commitment_fen`和`refund_pending`。实际可消费额度扣除未冻结AI任务预留；有欠费或待结算退款冻结时不能发起新付费消费。

Web套餐编号和原价格不变。后台将Apple消耗型商品绑定共同`sku_id`，冻结名称、Web标价、到账额度（包含套餐赠额）；已售商品不能改写映射。Apple参考价格与Web标价可不同，App显示StoreKit真实价格，服务端以验签交易实付金额记账。套餐变更需新建Apple商品，不重写历史交易。

共同下单请求：

```json
{"sku_id":"topup_10","pay_type":"apple_iap","idempotency_key":"每次新购买的UUID"}
```

响应包含共同充值`order_id/out_trade_no`、`intent_id`、`product_id`、`app_account_token`和冻结到账额度。StoreKit购买时传入该UUID；验单提交`{"signed_transaction_info":"Apple JWS","intent_id":123}`。`intent_id`可省略，用于通知先到、付款后退出App和未完成交易恢复。按`environment+transaction_id`去重，每笔真实付款分别对应一笔充值订单。只在服务端提交成功且允许`finish_transaction`后调用StoreKit `finish()`。

原`/api/marketplace/app/v1/iap/apple/*`和`/api/marketplace/payments/apple/notifications`保留兼容，调用相同服务，不重复入账。App的`GET /me/wallet`和`GET /me/wallet/entries`读取同一平台余额及流水；`POST /unlocks`继续使用发布版本、确认币数和幂等键。

Web只展示支付宝、微信；iOS只展示StoreKit。旧Web直接购买视频接口保留，只履约内容订单，不额外扣余额。任何渠道已取得同版本有效权益后，余额解锁直接返回已有权益。

## 消费、实收与退款

- AI按原价格预扣冻结，结束后按实际用量结算、按原来源退回未用额度；实际费用不足以支付时记录欠费，不写负可用余额。团队新任务仍扣团队所有者，历史团队钱包生命周期保留。
- 视频解锁在一个事务内扣余额、分摊来源、记录内容订单、发放永久版本权益及收益。不能占用AI冻结和排队预留。
- 实付按充值全部到账额度分摊，采用额度序号区间的累计取整；整批分摊金额精确等于真实付款。注册、管理员纯赠额的实收成本为0。视频收益按实际消费的现金成本与发布版本冻结比例计算，渠道费和税由平台承担。
- Apple退款使充值及附随赠额全部失效。命中视频消费时撤销整笔订单的授予、冲正收益，返还其他有效来源；该视频消费不再重复形成欠费。已经打款的创作者收益形成待抵扣，不改历史凭证。
- 已实际消耗的AI形成追偿，先扣其他有效未冻结额度，不足记欠费；返还和新到账资金优先补齐欠费。欠费期间暂停新付费AI调用和视频解锁，免费服务及其他有效权益可用。
- 冻结来源退款后阻止新的上游付费调用；在途调用继续轮询并按真实费用结算。未用的失效冻结不能返成可用余额。
- A充值用于AI后退款，B充值偿还；B再退款只重新打开A欠费，不产生第二笔同额欠费。A退款撤销时保留实际AI消费，取消对应欠费、返还有效B来源及应恢复原额度，不整批重复加款。
- 退款撤销不自动恢复已撤销视频权益。旧退款只撤回原订单授予，不能影响重新购买的权益。

消费信息分享需用户明确授权。对`CONSUMPTION_REQUEST`按Apple时限发送真实交付与消费数据；已消费可提交`DECLINE`建议，最终结果仍由Apple决定。不授权不阻碍购买，也不妨碍执行已确认退款。冻结不算实际消费。

所有资金操作先锁用户；AI保留`TaskRun→User`顺序。退款不持用户锁反向锁任务，由持久待办和调用前检查处理。Apple网络请求不放在资金数据库事务中。

## 后台与对账

入口仍在“业务→数字资产平台运营→App与苹果内购”，新增共同充值订单、资金来源、统一余额流水、欠费及偿还。后台金额以元显示，接口使用整数分。

Apple月度对账沿用原不可变交易事件，充值、退款和退款撤销分别核对。Web来源通过`POST /api/admin/marketplace/app/funding-reviews`登记真实收款凭据：`lot_id/channel_fee_fen/tax_fen/received_fen/note/idempotency_key`。净到账必须等于实付减渠道费和税，不提供无依据调差。所有资金来源完成核对后才允许创作者打款。

后台不能手工伪造Apple验单、退款或支付成功。缺少真实Apple配置时明确不可用；新购开关关闭后，已付款验单、通知、退款和补偿仍继续处理。

## 迁移、切换与回滚

本次代码交付不会自动执行本地业务余额切换。上线先备份，停新充值和新任务、排空所有AI在途任务；不能排空则不切换。在`backend`目录使用现有虚拟环境：

切换事务期间应停止API与任务执行进程，或在网关暂停全部资金写请求并返回可重试的503；仅隐藏充值按钮不够。来源迁入后立即核对并以统一开关开启的配置重启，不能让旧模式在此窗口继续入账。支付渠道重试的有效回调在恢复后按原订单幂等履约。

```powershell
python -m scripts.prepare_marketplace_app_schema
python -m scripts.prepare_marketplace_app_schema --check
python -m scripts.prepare_unified_wallet_schema --schema
python -m scripts.prepare_unified_wallet_schema --check
python -m scripts.prepare_unified_wallet_schema --report
python -m scripts.prepare_unified_wallet_schema --apply --backup-file "实际数据库备份路径"
```

`--schema`只新增统一资金结构；`--check/--report`不改余额。`--apply`要求统一开关关闭、真实非空备份文件，记录SHA256；锁定任务和相关资金表后重新核对。任一账户有无法解释的余额、冻结、实收来源或历史解锁映射则整体停止，不按面值猜现金。历史负余额转明确欠费。旧生产观影币只合入未用额度，保留成本区间和权益，不重放历史充值；Sandbox不并入生产。

核对完成后设置`UNIFIED_WALLET_ENABLED=true`并重启，再验证登录、共同余额、任务预扣和内容解锁。回滚应停新业务并保留资金处理，不直接切回会继续独立增减的旧钱包，不删财务历史。

离线契约导出：`python -m scripts.export_marketplace_app_openapi`。静态OpenAPI包含App接口及共同充值、余额、Apple验单通知路径，不包含真实凭证。真实Apple Sandbox、TestFlight、生产财务及OSS长播仍须分别联调；测试替身不代表真实支付验收。

## 本轮验证记录（2026-10-28）

- 已验证统一余额来源分摊、AI冻结及超额欠费、共同充值接口、Apple重复履约与退款、跨渠道权益、混合来源收益及迁移核对；包括历史来源篡改阻断、旧负余额立即偿还和偿还来源再次退款。
- 原计费、团队付款、市场发布、漫剧转存及App媒体相关回归410项通过；调度器开关与自动重启最终63项通过。调度维护新增项在统一开关关闭时不执行。
- 用户端和管理后台构建及lint通过；管理后台35项测试通过。现有lint警告和构建体积提示未作为业务验证结果。
- OpenAPI离线导出35个路径、38个操作，内部引用检查通过。
- 本轮没有对本地业务库执行结构迁移或余额切换，没有配置真实Apple凭证；真实支付、TestFlight与OSS长播不在已通过记录中。
