# 互动运营、精选置顶及作品分享

本次没有 AI 评论。App 的 `engagement.like_count`、`favorite_count`、`share_count` 已由服务器合计运营初始值和真实互动；客户端不得再次相加。`liked_by_me`、`favorited_by_me` 只代表当前账号真实行为。评论数量仍来自实际可见评论。

## 系统配置与上线

系统管理 → 站点设置提供：

- `marketplace_social_initialization_enabled`：默认关闭，只控制后续首次上架自动初始化。
- `marketplace_sharing_enabled`：默认关闭，控制新分享会话和完成事件。
- `marketplace_share_base_url`：公网 HTTPS 根域名，例如 `https://www.example.com`；禁止 localhost、私网 IP、非 HTTPS、子路径、用户名密码、查询参数及非443端口。
- `marketplace_share_apple_team_id`：Apple Developer Team ID；Bundle ID 复用现有 `apple_bundle_id`。
- `marketplace_share_android_package_name`：Android 应用包名。
- `marketplace_share_android_sha256_fingerprints`：实际安装包的签名证书 SHA-256 指纹，每行一条，支持签名轮换。两项安卓配置须一起填写或清空，与 Apple 配置互不依赖。

无需修改 `.env`。首次部署 API 自动使用现有统一数据库锁增量建表、补 `share_count` 列和检查结构，不重算历史余额或购买记录。迁移失败会记录原因并保护相关接口，原 API 继续运行；修复数据库后重启重试。

已有内容不会自动全部灌入初始值。数字资产平台运营 → 作品运营 → 历史内容初始化与任务恢复，先预览待补齐数量，再明确创建历史补齐任务。任务持久保存进度，关闭页面或重启后继续处理；失败项可重试。管理员明确提交的历史任务不受“自动初始化”开关影响。

## 统一作品运营页面

原互动运营和精选置顶合并为“作品运营”，使用封面卡片展示单视频、短剧系列和分集。支持名称搜索、内容类型、已加精/已置顶/普通状态筛选及分页。卡片展示作者、分类、上下架状态，以及点赞、收藏、分享的展示总数、真实数和初始值。

- 单视频：加精、置顶、修改互动数量、查看数量记录和原片预览。
- 短剧系列：加精、置顶；整体只展示真实互动，分集数量独立调整。
- 短剧分集：修改互动数量、查看数量记录和原片预览；无独立封面时使用系列封面，加精置顶在系列上设置。

页面保留批量加精置顶、运营审计和历史初始化任务。批量选择使用类型和编号共同识别目标，同编号的单视频和系列不会串联。修改数量及推荐配置仍要求原因、管理员权限和版本校验。

## 初始数量和管理员调整

单视频和短剧分集首次满足 App 可见条件后，分别生成点赞2001～12000、收藏2000～5000、分享500～3000，并满足分享＜收藏＜点赞。点赞下界2001是因为收藏最低2000且必须严格小于点赞。系列整体仅展示真实互动，不设置初始值，也不会汇总分集初始值。

初始记录只写一次，清零也保留初始化标记，不因刷新、重启、重新上架或发布新版本再次抽取。后续真实互动不强制保持上述比例。

接口仅管理员可用：

```http
GET   /api/admin/marketplace/app/social/metrics?target_type=work&page=1&page_size=20&q=&curation=
PATCH /api/admin/marketplace/app/social/metrics/work/123
GET   /api/admin/marketplace/app/social/metrics/events?target_type=work&target_id=123
POST  /api/admin/marketplace/app/social/initialization-jobs
GET   /api/admin/marketplace/app/social/initialization-jobs/456
POST  /api/admin/marketplace/app/social/initialization-jobs/456/retry
```

调整请求示例：

```json
{"version":1,"reason":"运营调整","like_count":6000,"favorite_count":3000,"share_count":1000}
```

三个输入是期望展示总数，不是增量。必须是0～10亿的整数且不得小于实时真实数。后端加锁后计算初始值；过期版本返回409。清零请求：`{"version":2,"reason":"恢复真实数量","clear":true}`。前台作品编辑接口不能修改这些字段。

列表的 `curation` 支持空值、`featured`、`pinned`、`normal`，筛选先于分页。分集搜索同时匹配系列名称；分集不具有独立精选置顶状态。卡片响应增加 `author`、`owner_id`、`cover_asset_id`、`asset_id`、`category`、系列及分集信息、审核/上架/封禁状态、`is_featured`、`is_pinned`、`pin_priority`、`curation_version`。`version` 仍是数量初始值版本，`curation_version` 是推荐配置版本，不可混用。

历史任务默认仅预览：`{"preview":true,"target_type":"work"}`；确认执行传 `preview:false` 及 `reason`。分集类型使用 `series_episode`，内部旧 `episode` 记录统一映射。真实统计周期对账只修正真实部分。

## 精选和置顶

作用于 `work` 和 `series`，Web 广场与 App 内容流共用配置。公开列表及详情只增加 `is_featured`、`is_pinned`，客户端用它们显示“精选 / Featured”“置顶 / Pinned”，不自行重排。分集目录继续按集号排列。

Web 默认推荐排序；App 使用 `GET /api/marketplace/app/v1/feed?sort=recommended`，支持 `sort=latest`。推荐顺序为置顶、置顶排序值、精选、发布时间、类型和ID，均按对应优先级降序；权重0～9999，默认100。明确选择最新或价格排序时不受运营优先级干扰。

先应用分类、搜索、价格、审核、版权、屏蔽作者及平台收录条件，再排序。下架和封禁立即不可公开查看，后台配置保留。加精置顶不改内容版本、冻结价格或已购权益。

```http
GET   /api/admin/marketplace/curation/work/123
PATCH /api/admin/marketplace/curation/work/123
POST  /api/admin/marketplace/curation/batch
GET   /api/admin/marketplace/curation/events?target_type=work&target_id=123
```

设置示例：

```json
{"version":0,"is_featured":true,"is_pinned":true,"pin_priority":100,"reason":"本周精选"}
```

首次版本为0；后续使用读取到的版本。批量请求为 `{"items":[{"target_type":"work","target_id":123,"version":1,"is_featured":true,"is_pinned":false,"pin_priority":100}],"reason":"调整推荐"}`，返回逐项结果，成功项保留，冲突项刷新后重试。

### App 分页必须处理

游标不透明，客户端原样传回，不能解析或重新拼接。新版包含完整排序键、筛选摘要和运营版本；切换排序、筛选或账号后清空游标。

运营调整后推荐分页可能返回 HTTP409，错误码 `MARKETPLACE_FEED_UPDATED`：清空旧列表和游标，从第一页重新请求。旧时间游标仅支持 `sort=latest`，不能用于推荐排序。点赞、收藏或分享增长不改变运营版本。`Accept-Language` 不改变排序。

## 作品分享与 iOS 接入

游客、登录用户均可分享 App 可见单视频和当前分集；不支持整个系列分享，也不导出视频。

```http
POST /api/marketplace/app/v1/works/123/share-sessions
POST /api/marketplace/app/v1/episodes/456/share-sessions
```

游客请求必须带随机、持久的匿名安装ID：`{"anonymous_id":"ios_installation_random_123456"}`，仅允许16～128位字母、数字、下划线、连字符。登录用户携带原 Bearer Token，身份按账号确定；无需设备指纹。服务器每身份每分钟最多接受10次会话创建。

返回 `token`、`expires_at`、`content_type`、`content_id`、`title`、`description`、`cover_url`、`url`。示例业务链接为 `https://www.example.com/s/<public_id>`，不含用户身份、播放令牌或原片路径。

1. 先准备好分享数据，再通过用户点击调用 `UIActivityViewController`。Web 也采用“准备链接 → 发送或复制”两步，保证 Safari 的用户手势有效。
2. `completionWithItemsHandler` 中，`completed=false` 上报 `cancelled`；完成复制上报 `copied`；其他完成动作上报 `completed`。
3. 上报 `POST /api/marketplace/app/v1/share-sessions/{token}/events`，正文为 `{"action":"completed","anonymous_id":"同一安装ID"}`；登录会话使用同一账号。
4. 成功返回 `ok`、`counted`、`action`、合计 `share_count`。计数无需客户端再加一。重复响应中的 `counted=true` 表示此会话已计数，不能再次累加。
5. iOS 在提交前持久保存待报事件；网络失败只重试原令牌和原动作，不重新发送作品。会话有效24小时，过期410后放弃统计补报；若需再次分享则新建会话。

分享期间保持创建时的账号或游客身份。切换账号或从游客登录后，重新准备分享，不能用新身份补报旧会话。Web 会检查身份变化并重置准备状态；身份不符返回404，不能无限重试。

同一身份对同一内容滚动24小时内最多增加一次真实分享数。取消、爬虫、预览和打开链接不计数；分享操作统计不能当作收件人已收到、已观看或奖励结算凭证。创建和完成事件均重新校验当前内容可见性。

配置缺失或关闭时返回503 `MARKETPLACE_SHARE_UNAVAILABLE`，不会生成本地假链接。App 的 capabilities 增加 `sharing_enabled`，用于控制按钮；实际配置完整性仍以创建接口为准。

### Universal Links 和代理

分享域名必须同时承载 Web 站点，并把 `/s/`、`/.well-known/apple-app-site-association`、`/.well-known/assetlinks.json` 代理到 API。仓库 `frontend/nginx.conf` 和本地部署示例已补齐；外层反向代理也必须放行。关联文件返回JSON，禁止跳转到SPA或登录页。Android 具体配置、Manifest、分享计数边界和真机验收见 [安卓接入说明](ANDROID_SHARING.md)。安卓无需配置 Apple 信息；普通分享链接只要求有效分享域名，两个平台的关联文件分别校验各自配置。

分享会话令牌与播放令牌均须从普通日志中去除。后端及仓库Nginx示例已处理 `/api/marketplace/app/v1/share-sessions/`，外层代理、CDN和客户端错误上报也应隐藏令牌路径；公开的 `/s/{public_id}` 是作品链接，可以正常记录访问，但打开链接不增加分享数。

iOS 设置 Associated Domains：`applinks:www.example.com`。关联文件覆盖 `/s/*`、`/marketplace/works/*` 和 `/marketplace/series/*`。客户端同时支持稳定分享链接和直接作品链接；读取链接 `/s/{public_id}` 后请求该HTTPS业务地址并解析服务器重定向目标：单视频为 `/marketplace/works/{id}`；分集为 `/marketplace/series/{series_id}?episode_id={id}`。只接受配置分享域名及这两种业务路径，客户端不得把任意重定向当作可信深链。未安装App时浏览器自然落地；Web 已增加 `episode_id` 定位，不覆盖到其他分集。

更新关联文件后，检查公网 `/.well-known/apple-app-site-association` 直接返回 200 和 JSON，不能重定向或返回首页；`appID` 来自系统管理中的 Team ID 与 Bundle ID，必须与安装包签名 entitlement 一致。若站点静态托管了关联文件，也须同步更新该文件。Apple CDN 存在缓存，服务端更新不代表设备立即生效；核对 CDN 内容后重新安装测试包，并从备忘录或信息点击两类链接验证。系列链接还需验证 `episode_id` 定位。

打开链接仍检查审核、下架、封禁及版权，遵守原免费完整播放/收费试看规则。分享链接不会赋予观看权益。真实系统分享、外网代理、AASA和App唤起须使用真实域名及iOS真机验收，单元测试不能代替这些联调。


## 后台积分解锁订单与分成权限

入口：业务 → 数字资产平台运营 → 视频解锁订单。仅展示全平台视频解锁订单，支持生产／沙箱环境、购买用户编号、订单状态筛选及分页；不展示个人钱包、平台余额汇总或苹果充值配置。沙箱订单不会出现在生产环境筛选结果中。扣除积分属于购买者，与创作者收益不同，收益请到收益账本查看。

作者发布、编辑单视频、系列及分集时不再提交 `share_bps`；包含此字段（即使为 null）的请求返回 422。作者更新其他资料不会清除运营已设置的比例。需要同步更新仍发送该字段的旧客户端。

平台默认比例在“平台分成”页设置；单独比例在“作品审核／短剧审核 → 详情”设置，分集跟随当前选集。仅管理员可通过 `PATCH /api/admin/marketplace/content-revenue/{work|series|series_episode}/{id}` 修改，提交 `version`、`previous_share_bps`、`share_bps` 和必填 `reason`。比例为万分比，null 表示继承，0 表示平台抽成零；过期内容或比例返回 409，操作写入审计。

优先级：分集 → 系列 → 平台；单视频为作品 → 平台。修改仅在后续提交发布时生成新快照采用，不追溯已提交的发布快照、已购权益、订单及收益；如需让现有内容采用新比例，按原流程更新并重新提交审核，历史买家继续持有旧版权益。无需数据迁移。
