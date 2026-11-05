# 积分展示约定 / Points display

互动合计数量、加精置顶排序与新版游标、作品分享及 Universal Links 接入见 [互动运营与分享说明](MARKETPLACE_OPERATIONS.md)。推荐分页收到 `MARKETPLACE_FEED_UPDATED`（409）时必须清空游标并刷新首页。

平台额度：1 元额度 = 100 积分。余额、冻结、欠费、消费、到账及赠额的整数 *_fen 和兼容 coins 字段直接作为积分显示，不乘除 100（10000 → 10,000 Points；25 → 25 积分）。视频解锁价格同理。iOS 页面由客户端团队同步修改。

充值实付、Apple 原币金额、版权参考价、创作者收益、渠道成本和打款仍使用货币。credit_currency=CNY 保留原协议含义。四档到账为 10,000 / 49,000 / 104,000 / 220,000 积分，支付售价不变。后端、历史数据、退款和扣费不变，无需迁移。未知历史人工文本不改写。

# App视频接口与Apple内购接入

固定人民币/美元档位、统一余额接口、外币核算及 StoreKit 2 示例见 [IOS_RECHARGE.md](IOS_RECHARGE.md)。Apple 充值独立于视频市场开关，支持 CNY/USD；本文早期仅人民币约定以该更新为准。

本模块提供App内容、HLS播放、Apple消耗型内购充值、余额解锁及人工财务运营。Web与iOS共用同一个PrintFilm账号、充值套餐和平台余额：Web易支付充值可在App解锁视频，Apple充值可在Web用于AI生成。唯一消费余额仍为`users.balance_fen/frozen_fen`，不再写入旧独立观影币钱包；资金来源、退款与迁移规则以[统一余额说明](UNIFIED_WALLET.md)为准。本仓库不包含完整iOS播放页面。

## 业务规则

- App收录已审核、上架且未被封禁或限制版权的免费公开和平台投放收益内容；版权出售收益不进入App内容流。
- 免费内容完整播放，收费内容未解锁时播放无水印短试看，最长15秒且不超过原片时长30%。收费短剧的前置免费集按现有规则判断，不以参考价为0判断免费。
- 按单视频或分集扣币，永久权益绑定`publication_id`。作者更新不替换已购视频，主动下架不撤销旧权益；封禁、删除及版权限制仍可能阻断播放。
- 平台余额底层使用整数积分，App兼容展示`1币＝1积分`；`balance_coins`与`balance_fen`是同一余额，不需要兑换。额度不失效、不转赠、不提现，创作者待结算收益仍单独对账打款。
- Web和Apple共用到账额度及套餐赠送规则，不修改现有套餐价格或编号。Apple商品是消耗型充值包，不为每个分集建商品；首期仅中国大陆商店、人民币交易。
- Apple商品绑定共同`sku_id`并冻结套餐版本。已创建的商品额度、参考价格和套餐绑定不能随意改写，调整档位须建立新商品。真实售价由StoreKit展示，记账使用Apple已验签交易的实际付款。
- Production与Sandbox必须使用独立部署、数据库、Redis和通知地址。生产服务拒绝Sandbox资金，测试余额不能进入生产账户。

## App接口

JSON业务前缀为`/api/marketplace/app/v1`，所有接口通过HTTPS访问。复用`POST /api/auth/login`和Bearer Token，App凭证存入Keychain，过期后重新登录。免费浏览和播放允许游客，充值、钱包和解锁必须登录；Apple ID不是PrintFilm账号。

### 互动功能开关

互动功能与 App 总开关分层控制。配置由后端启动时读取并缓存，修改环境变量后必须重启后端进程：

| 配置 | 作用 | 关闭时行为 |
| --- | --- | --- |
| 系统设置 → 站点工具 → 启用 App 视频服务 | App 内容、播放及新业务入口。保存后写入数据库，预发不需要容器环境变量 | 返回 `MARKETPLACE_APP_UNAVAILABLE`；不影响原 Web 市场接口。未保存过时默认关闭。API 启动仍使用统一数据库锁幂等补齐结构；已有付款履约不受入口开关控制。`MARKETPLACE_APP_ENABLED` 只在还没保存过时作为初始值 |
| `MARKETPLACE_SOCIAL_ENABLED` | 点赞、收藏、评论、举报和互动统计 | 互动接口返回 `MARKETPLACE_SOCIAL_UNAVAILABLE`；内容详情和播放仍可用 |
| `MARKETPLACE_COMMENTS_ENABLED` | 全局评论能力 | 点赞和收藏仍可用；评论和回复返回 `MARKETPLACE_COMMENTS_DISABLED`，已有评论不删除 |

`MARKETPLACE_SOCIAL_ENABLED` 和 `MARKETPLACE_COMMENTS_ENABLED` 默认值为 `true`，但只有 App 总开关和市场开关都开启时才会提供服务。创作者还可以对单个作品、短剧系列或分集关闭评论；该设置只禁止新评论和回复，历史评论保留。管理员隐藏、删除或恢复评论不受创作者开关影响。

`GET /api/marketplace/app/v1/capabilities` 返回 `social_enabled` 和 `comments_enabled`，App 应以这两个字段控制入口。关闭开关不会删除互动数据，重新开启后继续使用原统计和记录。

互动联调最小流程：游客请求详情确认 `engagement.like_count`、`comment_count`、`favorite_count` 可读；登录后调用 `PUT /works/{id}/like` 或 `PUT /episodes/{id}/favorite`，重复请求应幂等；再调用 `POST /works/{id}/comments` 验证评论开关和错误码。评论列表支持 `sort=hot|latest`、游标分页和 `GET /comments/{comment_id}/replies` 多级回复。测试结束后使用对应 `DELETE` 接口清理测试互动数据。

主后端通过市场接入点始终挂载 App 路由，随 API 管理 App 服务及原市场 Worker；仅更新文档或前端不会更新正在运行的后端。手动启动的 Windows 后端需要更新源码并重启原进程。先访问`/api/marketplace/app/v1/capabilities`确认路由与开关，再请求`/feed`：普通`{"detail":"Not Found"}`表示运行版本未挂载此路由；`MARKETPLACE_APP_UNAVAILABLE`表示市场或App入口关闭；结构未就绪返回`503 MARKETPLACE_APP_SCHEMA_REQUIRED`。没有可见作品时返回`200`和空`items`。API启动在同一数据库锁下自动进行内容、播放、互动及Apple/钱包的幂等增量迁移，不重算历史余额；迁移失败记录日志并保护相关接口。播放封装仅在开关和结构检查通过后使用原Worker执行。

局域网调试时，后端使用`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`监听，并将本地`PUBLIC_BASE_URL`设为手机可访问的`http://电脑局域网IP:8000`。仅监听`127.0.0.1`时，使用电脑的局域网IP访问会连接失败；播放会话返回的地址也必须使用局域网IP。正式环境使用HTTPS域名。

### 内容与已购

```http
GET /capabilities
GET /feed?q=&category=&content_type=all&sort=recommended&limit=20&cursor=
GET /works/{work_id}
GET /series/{series_id}
GET /series/{series_id}/episodes?limit=20&cursor=
GET /me/entitlements
```

`feed.content_type`为`all`、`work`或`series`，单页默认20、最多50条，返回`items`、`has_more`、`next_cursor`。短剧以系列卡片展示，目录按集号继续分页。游标由服务端生成，调用方原样传回，不自行拼接。

详情包含标题、作者、分类、封面、视频时长、显示宽高、横竖版、分集信息、发布版本、解锁币数及访问状态。作者在 `author` 中返回：`id` 为用户编号，`name` 为昵称，`avatar_url` 为头像地址；未上传头像时 `avatar_url` 为空字符串。列表、作品详情、短剧详情和分集列表使用同一结构，不返回邮箱。视频画幅在成片校验时写入资产，接口只读 `display_width`、`display_height` 和 `orientation`（`landscape` 横版、`portrait` 竖版、`square` 方形）。短剧系列卡片使用第 1 集视频的画幅，各集以分集接口自己的字段为准。没有记录时这三个字段为 `null`，列表不会因此失败，也不会在请求过程中下载原片。已购列表应以`publication_id`请求播放，不以当前作品编号替换旧版本；游客响应不能缓存成登录用户的权益。内容举报进入市场后台，屏蔽作者仅影响当前用户发现列表，不删除已购记录。

### 播放会话

```http
POST /playback-sessions
GET /playback-sessions/{token}/index.m3u8
GET /playback-sessions/{token}/segments/{segment_id}
```

当前内容请求：`{"content_type":"work","content_id":123}`，短剧使用`series_episode`。历史已购版本请求：`{"publication_id":456}`。两种定位方式二选一，不提交视频地址或OSS键。

响应含`session_id`、`playback_url`、`format:"hls"`、`access_mode`（`free`/`preview`/`entitled`）、`publication_id`、`expires_in:1800`和`max_lifetime_seconds:7200`。App将HTTPS播放地址直接交给AVPlayer。

会话空闲30分钟失效、最长2小时；持续取分片延长空闲时间。暂停超时或Redis重启后，重新申请会话并恢复播放位置。重新登录、网络恢复或链接过期时重新申请，不长期保存播放URL。

分片接口鉴权后签发60秒OSS地址，由OSS传输视频；权益及版权限制缓存最多15秒。退款或封禁停止新签发，已签链接和客户端已缓冲内容不能立即撤回。禁止记录完整会话令牌、签名链接和Apple JWS。

API业务日志与Uvicorn访问日志已隐藏播放路径中的令牌。本仓库`deploy/nginx.local.conf`也对`/api/marketplace/app/v1/playback-sessions/`设置`access_log off`；生产反向代理及CDN需采用相同规则或路径脱敏，不能将令牌路径和OSS签名参数收集到普通访问日志、分析系统或错误上报正文。

App完整播放统一HLS：兼容源无损封装，不兼容时保持源分辨率生成兼容版本，保留原片，不强制降到720p。免费内容不裁剪、不加水印；Web免费原片接口保持不变。继续使用市场Worker及看门狗，不增加独立进程。首期不提供FairPlay DRM和离线下载，不能保证阻止录屏或复制。

### 充值、钱包与解锁

共同支付入口为：

```http
GET  /api/billing/skus?channel=apple_iap
GET  /api/billing/wallet
POST /api/billing/orders
POST /api/billing/apple/transactions/verify
POST /api/billing/apple/notifications
```

`POST /api/billing/orders`提交`{"sku_id":"后台已绑定的共同套餐编号","pay_type":"apple_iap","idempotency_key":"此次购买的UUID"}`。响应提供共同充值订单、Apple商品和`app_account_token`，不返回易支付跳转地址。Web继续使用`alipay/wxpay`，iOS只展示StoreKit入口。

以下App兼容接口调用同一资金服务，不创建第二份余额：

```http
GET /coin-products
GET /me/wallet
GET /me/wallet/entries
POST /iap/apple/purchase-intents
POST /iap/apple/transactions/verify
PATCH /iap/apple/consumption-consent
POST /unlocks
GET /me/unlock-orders
```

先取得服务端启用的苹果商品编号，再用StoreKit查询真实可售商品和本地化价格；不能只显示后台配置价并声称商品已在苹果可售。充值意向绑定当前账号的稳定`appAccountToken`，App在`Product.purchase`时传入该UUID。

服务端验证Apple签名、App身份、环境、商品、账号归属、币种及退款状态后，原子保存共同充值订单、渠道交易、来源批次和统一资金流水，并优先抵扣已有欠费。只在服务端已提交确认后`finish()`；断网或响应丢失时重传原交易，不重新购买。`environment + transaction_id`全局去重；多笔真实付款分别入账。

创建充值意向的请求与响应：

```json
{"product_id":"已配置的苹果商品编号","idempotency_key":"每次新购买生成的UUID"}
```

响应包含`intent_id`、共同`order_id/out_trade_no`、`sku_id`、`product_id`、`credit_fen/coins`、`price_fen`、`currency`、`app_account_token`、`environment`和`expires_at`。相同购买重试复用幂等键；`app_account_token`传入StoreKit的`.appAccountToken(UUID)`。`price_fen`是商品参考价格，不代替StoreKit实际售价。

验单请求为`{"signed_transaction_info":"StoreKit提供的完整JWS","intent_id":123}`，`intent_id`可省略，以便恢复未完成交易。响应包含`transaction_id`、`environment`、`status`、`coins`、`amount_fen`、`currency`、`credited`、`finish_transaction`、`message`、`balance_coins`。仅服务端响应允许`finish_transaction=true`后调用`finish()`；退款交易可能允许结束交付但不会增加余额，不能只检查HTTP成功或`credited`。

扣币解锁请求：

```json
{"publication_id":456,"expected_coins":100,"idempotency_key":"此次解锁生成的UUID"}
```

服务端核对可售状态、价格、欠费和实际可消费余额，一次事务完成扣款、FIFO来源分摊、内容订单、永久权益与收益，不能占用AI冻结或排队预留。已有任一渠道的有效权益直接返回，不重复扣款。同一次解锁重试复用幂等键；价格或版本冲突先刷新详情、让用户重新确认，不能自动按新价格扣款。钱包流水和解锁历史使用`cursor`与`page_size`（默认20、最多50），返回`items`、`has_more`与`next_cursor`。具体字段以`/docs`中的OpenAPI为准。

钱包响应中的`balance_fen/balance_coins`是同一可用余额，`frozen_fen`为已冻结额度，`debt_fen`为欠费，`spendable_fen`扣除了未冻结AI任务预留。有欠费或`refund_pending=true`时不能发起新的付费消费；不要仅凭余额大于零启用解锁按钮。

消费信息授权默认关闭。App如提供开关，调用`PATCH /iap/apple/consumption-consent`，请求`{"consented":true}`或`{"consented":false}`；向用户说明仅在退款处理时向苹果提供该笔充值的到账状态和使用比例。不授权不影响购买，也不阻止处理苹果退款结果。

**已finish的消耗型购买不能靠常规“恢复购买”重建余额。** 换机、重装后登录PrintFilm，通过服务端钱包、充值历史和已购权益恢复。App启动监听`Transaction.updates`及未完成交易；不同PrintFilm账号不能认领同一Apple交易。

## StoreKit 2集成顺序

以下Swift只说明调用顺序，`backend`由App团队按OpenAPI实现；私钥、Apple API JWT及服务端验签逻辑不能放入App。

```swift
// App启动即监听，不随播放页面离开而取消整个交易监听。
func listenForTransactions() async {
    for await result in Transaction.updates {
        await deliver(result)
    }
}

func purchase(product: Product, accountToken: UUID) async throws {
    let outcome = try await product.purchase(options: [.appAccountToken(accountToken)])
    switch outcome {
    case .success(let verified): await deliver(verified)
    case .pending: break // 等待Apple更新，不能提前加币。
    case .userCancelled: break
    @unknown default: break
    }
}

func deliver(_ result: VerificationResult<Transaction>) async {
    guard case .verified(let transaction) = result else { return }
    do {
        // 客户端验证通过不等于后台到账，将JWS提交服务端确认。
        let confirmed = try await backend.confirmAppleTransaction(result.jwsRepresentation)
        // Swift解码使用convertFromSnakeCase：finish_transaction -> finishTransaction。
        if confirmed.finishTransaction { await transaction.finish() }
    } catch {
        // 保留未完成交易稍后重试；账号冲突时提示登录原PrintFilm账号。
    }
}
```

充值成功后刷新钱包，用户明确确认内容和币数后才请求解锁。充值到账不等于某个分集已解锁。取得服务端永久权益后申请完整播放，不在客户端自行决定原片地址。

App还应提供举报、屏蔽及取消屏蔽入口：

```http
POST   /reports
GET    /me/author-blocks
PUT    /me/author-blocks/{author_id}
DELETE /me/author-blocks/{author_id}
```

举报请求例：`{"target_type":"series_episode","target_id":123,"statement":"具体侵权或违规情况，至少十个字","contact":"可联系的方式","evidence_ids":[]}`。举报支持`work`、`series_episode`，证据沿用现有市场私有材料上传；屏蔽和取消屏蔽无请求体。

常见错误处理：`MARKETPLACE_COIN_BALANCE_INSUFFICIENT`提示充值；`MARKETPLACE_CONTENT_CHANGED`刷新内容后重新确认；`MARKETPLACE_EPISODE_NOT_READY`提示播放准备中，不能循环扣币；`MARKETPLACE_PLAYBACK_SESSION_EXPIRED`重新创建会话并续播；`MARKETPLACE_IAP_ACCOUNT_MISMATCH`提示登录原PrintFilm账号；`MARKETPLACE_PAYMENT_UNAVAILABLE`、`MARKETPLACE_STORAGE_UNAVAILABLE`或`MARKETPLACE_PLAYBACK_UNAVAILABLE`明确提示暂不可用，不显示到账或播放成功。

## 退款、收益与人工结算

共同通知地址`POST /api/billing/apple/notifications`使用App Store Server Notifications V2，原`POST /api/marketplace/payments/apple/notifications`保留兼容。先验签、持久化再确认接收；客户端验单、通知和补偿查询复用同一履约函数。市场展示或新购关闭后仍处理有效付款、退款和补账。

- 充值先抵欠费，再增加未消费余额，不产生创作者收益；解锁按扣款对应的真实充值金额分摊，并使用发布版本冻结比例。套餐赠额包含在实付分摊中，注册、管理员纯赠额的现金成本为0。金额用整数分、批次累计取整，平台分成向下取整、余数归创作者。
- 按用户实付总额分成，Apple渠道费及税费由平台承担，不重复扣创作者比例；平台净收益允许为负。
- Apple退款使该充值及附随赠额失效，扣回尚未使用部分；命中视频解锁时撤销原订单授予、冲正整笔收益，返还其他有效来源后优先补欠费。同一订单只冲正一次，已撤销视频消费不再重复形成欠费。
- 已实际消耗的AI费用先由其他有效未冻结余额抵扣，不足记明确欠费。后续充值和返还先补齐欠费；欠费期间暂停新的付费AI调用和视频解锁，免费服务及其他有效权益不受影响。
- 退款来源中已冻结的额度标记失效，阻止尚未开始的付费调用；已在途调用照实结算。失效来源的未用冻结不能退成可用余额。
- 不能撤销退款后重新购买的新权益。已打款收益形成待抵扣记录，不改写旧打款。
- Apple撤销退款时按原消费和偿还关系恢复：保留实际AI消费，取消对应欠费，返还仍有效的代偿来源和应恢复的原额度，不能整批重复加款。已撤销视频权益不自动恢复，用户可重新解锁。
- A充值用于AI后退款、B充值补欠费，B再退款只重新打开A欠费；A退款撤销不能再次把整批A额度加回。所有偿还保留来源和反向记录。
- `CONSUMPTION_REQUEST`是消费信息请求，不代表退款成功。经用户有效授权后在Apple规定的12小时内发送真实交付及消费信息；冻结不算实际消费，已消费可建议`DECLINE`，最终决定仍由Apple作出。重复和乱序事件核对Apple权威交易后再应用。
- 按月核对Apple财务报告，关联充值、渠道费、税费和实收；全部来源对账完成的收益才可人工打款。打款关联收益账目，校验退款抵扣及可结算金额，不支持自动转账。

管理入口：「业务 → 数字资产平台运营 → App与苹果内购」。市场关闭时仍可进入App财务；生产和Sandbox分开。后台不显示私钥、JWS及原始支付载荷。财务输入以元展示、接口以分保存；失败重试沿用幂等键，修改表单为新操作。

后台独立前缀`/api/admin/marketplace/app`，须管理员Bearer Token。列表除原有商品、交易、通知、钱包、解锁、收益、对账和打款外，还包括`GET /recharge-orders`、`/funding-sources`、`/debts`、`/repayments`和`/funding-reviews`，均返回`items`与`meta:{page,page_size,total}`；默认20条。环境参数不能把另一个部署的余额合入当前数据库。账户、交易、解锁和收益按服务端支持的用户或创作者编号筛选。

`PUT /products`提交`product_id`、`sku_id`、`coins`、`price_fen`和`enabled`。`coins`必须等于共同套餐的`credit_fen`（包含赠额），不要求等于商品参考价。已绑定商品只能启停；旧未绑定商品只有在额度与共同套餐一致时才可人工补充绑定，不猜测历史映射。失败通知通过`POST /notifications/{id}/retry`重新核验；失败播放准备通过`POST /media/{id}/retry`重新排队，均不能手工伪造到账或退款。

`POST /funding-reviews`登记Web资金来源的真实收款核对，提交`lot_id`、`channel_fee_fen`、`tax_fen`、`received_fen`、`note`和`idempotency_key`；不增减用户余额。净到账必须等于实际收款减渠道费和税费。混合Web及Apple来源的收益须全部完成核对才可打款。

`POST /settlements`提交`environment`、`month`（`YYYY-MM`）、`transaction_ids`、`channel_fee_fen`、`tax_fen`、`received_fen`、`note`、`idempotency_key`。接口自动纳入所选交易当前版本之前尚未对账的不可变事件：充值为正金额、退款为负金额、退款撤销为正金额；首次观察时已退款且未加币的初始记录为0。渠道费及税费非负；净到账允许为负，必须等于本次事件净额减渠道费和税费，不提供人为调差绕过核对的入口。退款或撤销后交易重新成为待对账；原幂等键重试只返回冻结的旧报表，不把后续事件标为已对账。

`POST /payouts`提交`owner_id`、`environment`、`ledger_ids`、`amount_fen`、`note`、`idempotency_key`；金额必须等于选中可结算收益扣除历史退款待抵扣金额，全额抵扣时允许0元，仍保留关联明细。Sandbox仅用于测试，后台不登记真实财务对账或打款。

## 配置、迁移、上线与验收

默认关闭App开放和Apple新购。真实启用需准备开发者账号、App及Bundle ID、有效付费协议、税务和收款资料、消耗型充值商品、服务器API密钥、Apple根证书、生产/Sandbox通知HTTPS地址、Redis及私有OSS。密钥仅保存在服务端，不能提交仓库。

独立配置位于服务端`backend/.env`，由`app/marketplace/app_settings.py`读取；`backend/.env.example`提供全关闭的业务开关及空白凭据模板。开关默认值如下，其余项目必须使用真实配置：

```dotenv
UNIFIED_WALLET_ENABLED=false
MARKETPLACE_APP_ENABLED=false
MARKETPLACE_APPLE_IAP_ENABLED=false
MARKETPLACE_APPLE_ENVIRONMENT=Production
MARKETPLACE_APPLE_ONLINE_CHECKS=true
```

- `MARKETPLACE_APPLE_BUNDLE_ID`：App的Bundle ID。
- `MARKETPLACE_APPLE_APP_ID`：App Store Connect中的数字App ID；未配置时省略，启用生产前填写真实正整数。
- `MARKETPLACE_APPLE_ISSUER_ID`、`MARKETPLACE_APPLE_KEY_ID`：App Store服务器API凭据标识。
- `MARKETPLACE_APPLE_PRIVATE_KEY_PATH`：仅服务端可读的真实`.p8`私钥文件路径。
- `MARKETPLACE_APPLE_ROOT_CERT_PATHS`：Apple官方Root CA的DER证书文件路径，多个文件以分号分隔；SDK要求DER，不使用PEM，不使用客户端提交的证书，也不自动联网下载证书。
- `MARKETPLACE_APPLE_ENVIRONMENT`：生产使用`Production`，Sandbox服务使用`Sandbox`；由服务器选择，客户端不能任意切换钱包环境。

生产与Sandbox必须使用独立服务端部署、数据库、Redis及通知地址，仅增加`environment`字段不足以隔离共用的`users`余额。`MARKETPLACE_APPLE_ENVIRONMENT`由服务器配置，生产拒绝Sandbox资金。共同套餐和Apple固定映射分别在对应部署维护，真实可售状态及售价仍由App Store Connect和StoreKit决定。

API 启动时会在同一个 PostgreSQL advisory lock 内自动执行数字资产 App 的幂等增量结构迁移，覆盖内容、播放、互动、Apple、钱包、退款和收益表。只新增缺失表、列和索引，不删除或改写历史数据；结构迁移失败时 API 不会通过健康检查。以下脚本保留给离线核验或故障恢复使用：

```powershell
python -m pip install -r requirements-apple.txt
python -m scripts.prepare_marketplace_app_schema
python -m scripts.prepare_marketplace_app_schema --check
python -m scripts.prepare_unified_wallet_schema --schema
python -m scripts.prepare_unified_wallet_schema --check
python -m scripts.prepare_unified_wallet_schema --report
python -m scripts.prepare_unified_wallet_schema --apply --backup-file "实际数据库备份路径"
```

Apple官方服务器库固定在`requirements-apple.txt`（`app-store-server-library==3.1.2`），常规`requirements.txt`已包含它。App结构迁移增加渠道凭证和共同订单引用；统一钱包`--schema`建立独立的`wallet_`资金来源、消费及欠费表，`--check/--report`只读。`--apply`必须在统一开关关闭、停止新充值和新任务、排空在途任务后运行，并验证真实非空备份文件、保存SHA256；任一账户来源、余额、冻结或历史消费不一致时整体停止。旧生产观影币仅合入未用额度并保留原区间及权益，不重放充值；历史负数转明确欠费。详见[完整切换说明](UNIFIED_WALLET.md)。

迁移不会自动启用功能。核对通过后再设置`UNIFIED_WALLET_ENABLED=true`、重启并验收；未迁移账户返回明确不可用，App资金功能不回退旧独立钱包。结构通过不代表真实支付和播放联调通过。进程启动仍使用现有后端启动命令及市场Worker看门狗。

App团队可直接导入本仓库的[OpenAPI交付文件](openapi/marketplace-app-v1.json)。后端接口改动后，在`backend`目录使用同一虚拟环境重新导出：

```powershell
python -m scripts.export_marketplace_app_openapi
```

默认更新`docs/openapi/marketplace-app-v1.json`，可用`--output`指定其他交付位置。离线导出包括App v1、共同充值/余额/Apple验单通知和App运营路由，不启动Worker、不连接数据库或Apple服务，不包含真实部署地址、账号或密钥；输出前检查内部`$ref`及已注册操作。在线`/docs`仍可查看整个项目实时接口。

发布顺序：

1. 备份整个PostgreSQL库，覆盖全部`marketplace_`表；OSS对象另行备份。
2. 保持统一余额、App及新购开关关闭，暂停新资金业务和AI任务、排空并结算在途任务；安装依赖，执行App及统一钱包结构检查、来源报告和带备份凭证的切换；非零即停止。
3. 核对通过后开启统一余额、重启后端和后台，核对共同余额、权限、Web与AI回归；App及Apple新购仍关闭。
4. 配置真实商品、通知、证书和密钥，执行Sandbox及TestFlight验收，测试账目不进入生产。
5. 先开放免费内容，再小范围开放充值与解锁，持续核对余额、通知待办、退款与收益差异。

回滚只停新入口、新充值和新解锁，保留新增表、流水、历史权益及财务处理器；完成统一切换后不能直接切回会独立增减余额的旧实现。不得通过清空钱包、删除交易或降级表结构回滚。缺OSS、Apple或Redis配置必须报明确不可用，不能造假余额或播放链接。

验收覆盖：免费单视频和系列、收费系列免费集、短试看、旧版本权益、上下架及版权限制；超过30分钟播放、拖动、换网、前后台和Redis重启；重复验单、通知先到、付款后杀App、丢响应、双设备、跨账号；余额不足、价格冲突、混合批次退款及乱序；余额/流水/批次/收益可核对，打款不超可结算金额。

本地替身测试验证权限、状态、幂等、账务及媒体边界，不能作为真实Apple付款、OSS上传、iOS播放或财务对账验收。真实Sandbox、TestFlight、生产Apple及OSS结果必须单独记录，未完成前不能宣称可直接上线。

### 历史验证记录与当前验收边界

- 旧独立观影币版本曾有后端335项记录，仅作历史参考。本轮统一资金、共同充值、Apple退款、混合来源收益及迁移已重新验证；原业务相关410项、调度与自动重启63项、后台35项通过，前后台构建及lint通过。完整边界见[本轮统一余额验证记录](UNIFIED_WALLET.md)。各组含交叉用例，不合并为独立用例总数。
- FFmpeg实际执行H264无重编码HLS封装及VP9同分辨率兼容转码；数据库并发测试使用派生测试库和随机隔离schema。
- OSS、Redis会话和Apple网络边界使用测试替身，不代表真实上传、30分钟以上iOS播放或真实支付通过。
- 当前交付没有执行本地业务库的App增量迁移或统一余额切换，统一余额、App与Apple新购默认关闭；启用前按上文备份、迁移并检查。真实Apple Sandbox、TestFlight、生产财务及OSS联调均需单独执行，不能把测试替身结果记作通过。

官方参考：[Apple内购配置](https://developer.apple.com/help/app-store-connect/configure-in-app-purchase-settings/overview-for-configuring-in-app-purchases/)、[App Store服务器通知](https://developer.apple.com/documentation/appstoreservernotifications)。
# 中英文接口约定

App 请求使用 `Accept-Language: zh-CN` 或 `en-US`，缺省中文；读取 `Content-Language` 并按语言缓存。新增 `GET /api/marketplace/app/v1/categories`，列表支持 `category_code` 筛选（优先于旧 `category`）。业务代码不翻译，显示采用 `category_label`、`content_type_label`、`sale_type_label`、`access_mode_label` 等字段。人民币金额、权益和发布版本不随语言变化。完整契约、迁移和示例见 [MARKETPLACE_LOCALE.md](MARKETPLACE_LOCALE.md)。

# Android 分享接入补充

Android 与 iOS 共用作品分享、内容和播放接口；系统分享、App Links 配置和安卓事件上报口径见 [ANDROID_SHARING.md](ANDROID_SHARING.md)。后台可配置包名及多个签名证书 SHA-256 指纹，域名验证文件为 `/.well-known/assetlinks.json`。Android 不能把选中分享应用当作发送成功，首期仅复制成功计入可确认的真实分享。
