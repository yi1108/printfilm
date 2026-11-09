# API 接入与中文文档

接口定义由 FastAPI 路由和 Pydantic 模型实时生成，请以运行中服务的 OpenAPI 为准。

## 文档入口

本地后端默认地址为 `http://127.0.0.1:8000`。

| 入口 | 用途 |
| --- | --- |
| [/docs](http://127.0.0.1:8000/docs) | Swagger 在线调试，可按中文分组浏览和搜索接口 |
| [/redoc](http://127.0.0.1:8000/redoc) | ReDoc 阅读视图 |
| [/openapi.json](http://127.0.0.1:8000/openapi.json) | OpenAPI 定义，供客户端生成及接口工具导入 |

这些地址由后端提供。通过前端站点访问时，需要网关显式转发对应文档路径；当前用户端 nginx 的 `/api/` 代理不包含 `/docs`、`/redoc` 和 `/openapi.json`。

## 登录与调用

1. 使用 `POST /api/auth/register` 注册，或使用 `POST /api/auth/login` 登录。
2. 从响应读取 `access_token`；`token_type` 为 `bearer`。
3. 在 Swagger 的 **Authorize** 中填写令牌，或在请求头携带 `Authorization: Bearer <access_token>`。
4. 管理端 `/api/admin/...` 要求账号角色为 `admin`，普通登录令牌不会自动获得管理权限。

登录请求示例：

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "creator@example.com",
  "password": "your-password"
}
```

登录响应结构：

```json
{
  "access_token": "<login-jwt>",
  "token_type": "bearer"
}
```

### 注销当前账号

已登录用户可调用 `POST /api/auth/close-account` 永久注销当前账号：

```http
POST /api/auth/close-account
Authorization: Bearer <login-jwt>
Content-Type: application/json

{
  "password": "your-current-password",
  "confirmation": "DELETE"
}
```

成功响应为 `{"ok": true}`。服务端立即将邮箱、昵称、手机号、头像及密码匿名化，写入 `closed_at` 注销墓碑并撤销有效团队成员资格；同一账号此前签发的 JWT 与注销前签发的密码重置令牌随即失效。必要账单、余额及历史外键记录保留，不物理删除用户行。

密码错误或确认词不是精确的 `DELETE` 时返回 400；存在 `owner_user_id` 属于当前用户的团队，或当前用户发起/付费的任务尚未结束时返回 409。调用方应先转让或删除名下团队，并等待任务到达 `succeeded`、`failed` 或 `cancelled` 终态。未登录及已注销令牌返回 401。

查询个人漫剧项目示例：

```http
GET /api/drama/projects?workflow=script&page=1&page_size=9
Authorization: Bearer <login-jwt>
```

## 短片创作与历史项目

当前新建短片采用 `/api/projects` 分步创作流程：准备文案、创建或更新项目、生成分镜与素材，再由用户确认后合成成片。

`POST /api/projects` 与 `PATCH /api/projects/{project_id}` 使用 `pipeline_mode` 区分制作方式：

| 模式 | 素材与生成顺序 |
| --- | --- |
| `full` | 分镜脚本 → 参考图模式生成分镜图片 → 图片生成镜头视频 → 合成成片 |
| `image_text` | 分镜脚本 → 参考图模式生成分镜图片与配音 → 静图合成成片 |

当前新建页面默认选择 `full`，仍可选择 `image_text`。图片沿用选定模板的画风参考图、项目 `ref_image_url` 及已有镜头参考，锁定画风和角色；镜头视频以本镜图片作为首帧，并参考上一镜尾帧保持衔接。`image_model` / `video_model` 分别选择图片与视频模型，`image_resolution` / `video_resolution` 保存相应清晰度，`target_duration_sec` 为 15～180 秒的目标时长。完整视频模式沿用原有视频内置口播逻辑；静图模式保留外部配音。

画风图优先取模板 `seedream_config.style_ref_urls`，未配置时取模板封面；四个内置画风的旧模板行即使封面为空，也使用随代码提供的封面图。历史 `ref_images` 继续作为主体参考，用户图优先；后镜另加上一镜图片，画风参考独立传递。真实生成时，本地图片需同步发布到 OSS 或通过公网 `PUBLIC_BASE_URL/static/...` 访问，无法访问时返回明确错误，避免静默变成纯文字生图。镜头图片与视频参考均跳过需要鉴权的 TokenFree 产物地址，使用已保存的媒体。

调用 `POST /api/projects/{project_id}/generate` 每次只提交当前待执行的一段任务，阶段由后端素材就绪状态判定：`script`、`assets`、`videos`。素材阶段完成后，完整模式再次调用生成接口才进入视频阶段；静图模式跳过视频阶段。全部素材就绪时生成接口返回 409，改用 `POST /api/projects/{project_id}/compose` 合成。各阶段仅预扣本次尚未完成的媒体费用，已有图片和视频会复用。

单镜调整可使用 `POST /api/projects/{project_id}/shots/{shot_id}/regen-image` 与 `.../regen-video`；后者仅支持 `full`，并要求该镜已有图片。生成期间不能切换制作模式；通过 PATCH 切换模式会保留原分镜素材，作废原成片并按新模式回到待生成或待合成阶段。若要重新拆分镜，可调用生成接口并设置 `restart=true`，这会清除原分镜和素材。

旧版对话创作会话的创建、列表、详情、消息、取消、重试与 SSE 接口已删除，访问这些旧入口返回 404。其前端会话状态与轮询代码也已移除。

仅保留 `POST /api/creation-sessions/{session_id}/open-editor`，归入“科普项目与作品”分组，用于将历史项目转入当前工作台。该接口会先等待旧任务停止并结算，再交接原项目及素材；历史任务执行与恢复代码、数据库记录保留。

## 团队空间与编辑租约

支持空间切换的列表和创建接口通过 `X-Team-Id` 请求头或 `team_id` 查询参数选择团队空间；两者同时提供时必须一致。未指定时使用个人空间。资源详情和写入的权限依据数据库中的真实归属判定，切换请求头不能改变资源归属。

创建漫剧项目还可在请求体设置 `team_id`，与显式选中的团队空间不一致时返回 422。

团队漫剧内容写入通常先获取编辑租约：

```http
POST /api/teams/12/edit-locks/acquire
Authorization: Bearer <login-jwt>
Content-Type: application/json

{
  "project_id": 34,
  "resource_type": "structure",
  "resource_id": 0,
  "session_id": "editor-tab-001",
  "force": false
}
```

项目和团队编号为示例，请替换为实际可访问资源。获取成功后保存响应中的 `token`、`version`，写入时携带：

```http
PATCH /api/drama/projects/34
Authorization: Bearer <login-jwt>
Content-Type: application/json
X-Edit-Session: editor-tab-001
X-Edit-Token: <acquire 返回的 token>
X-Edit-Version: <acquire 返回的 version>

{
  "title": "新的项目名称"
}
```

`structure`、`script`、`canvas` 的 `resource_id` 为 0。已有资产使用资产编号；创建资产或未绑定既有资产的生成入口使用 `asset/0`，以具体接口为准。分集优先使用稳定集号，历史数据缺少集号时使用分集数据库编号。按实际写入范围申请租约，成功获取的租约默认有效期为 120 秒，可通过 `/renew` 续租、`/release` 释放；两者请求体为 `token` 和 `session_id`。续租不会再次返回原始 `token`，客户端应保留首次获取的凭证。

其他会话占用可返回 423；缺少租约返回 428；租约失效、版本变化或目标不匹配返回 409。强制接管人工占用仅团队所有者和管理员可用，不能绕过系统任务写入占用。取消生成入口等例外以具体接口说明为准。

## 漫剧项目字段约定

| 字段或参数 | 说明 |
| --- | --- |
| `source` | 原始创意，去除首尾空白后至少 20 字 |
| `workflow` | `script` 为剧本分集流程，`canvas` 为自由画布 |
| `episode_count` | 创建请求中的目标集数为 1～120；返回详情中的同名字段是已建立的分集数量 |
| `params` | 创建时与工作流配置一起保存；PATCH 时整体替换原配置，请保留仍需使用的键 |
| `content` | PATCH 时整体替换对象或数组，不做增量合并 |
| `q` | 标题子串搜索，忽略首尾空白及大小写；`%`、`_` 按普通字符匹配 |
| `status` | 项目列表进度筛选，依据剧本、资产与分集数量判断，不表示后台任务状态 |
| `usage` | 当前空间可见用量；团队所有者查看团队合计，其他成员仅查看本人用量 |

列表 `status=running` 和 `status=done` 可以重叠：漫剧有剧本且至少 1 集即符合 running，有剧本且至少 8 集符合 done；自由画布已有资产符合 running，不进入 done。`draft` 表示无资产的画布或无剧本的漫剧。详细规则见 Swagger 参数说明。

`GET /api/drama/canvas/{project_id}` 返回节点时，已有资产的 `mediaUrl`、`url`、`cover` 以服务端当前资产为准。`POST /api/drama/canvas` 保存布局时不会用客户端旧节点覆盖已有资产的视频、图片或封面地址；个人节点名称、提示词与布局仍按提交内容保存，上传和明确更换媒体继续使用资产接口。

## 分页、任务与错误

分页通常使用 `page`（从 1 开始）与 `page_size`，返回 `items` 和 `meta.page`、`meta.page_size`、`meta.total`。部分接口使用平铺分页字段或直接返回数组，请以各自响应结构为准。漫剧项目列表会将超出范围的页码修正为最后一页。

生成接口可能在请求内完成，也可能提交后台任务。异步接口返回成功表示任务已受理，最终结果需查询 `/api/tasks/{task_id}`、`/api/tasks/generations/{task_id}` 或对应业务状态接口。SSE 接口使用 `text/event-stream`，事件名和数据内容见接口说明。任务调度与状态详见 [TASK_SCHEDULING.md](./TASK_SCHEDULING.md)。

错误响应的 `detail` 可能是中文字符串、结构化对象或字段校验数组。客户端应同时检查 HTTP 状态码和 `detail`，不要假定所有接口共用成功响应封装。

| HTTP 状态 | 常见含义 |
| --- | --- |
| 400 | 业务参数或当前操作不符合要求 |
| 401 | 未登录或登录令牌失效 |
| 403 | 当前账号没有操作权限 |
| 404 | 资源不存在、不可访问或对应模块未启用 |
| 409 | 状态、版本或编辑权限冲突 |
| 410 | 接口已停用，例如团队钱包充值与调账兼容入口 |
| 422 | 字段、参数组合或媒体参数校验失败 |
| 423 | 资源正在被其他成员或任务占用 |
| 428 | 缺少团队内容编辑租约 |

金额字段 `*_fen` 的单位为人民币分，`*_yuan` 为人民币元；其他价格与 Token 费率以字段说明为准。团队创作当前由所有者个人钱包付费，历史团队钱包入口不代表仍支持团队充值。详见 [BILLING.md](./BILLING.md) 和 [TEAM_MODE.md](./TEAM_MODE.md)。

个人充值先查询 `GET /api/billing/skus` 的 `pay_types`。`POST /api/billing/orders` 接受 `sku_id` 和 `pay_type`（`alipay`、`wxpay`，以及启用并配置后的 `stripe`）；套餐金额与到账额度由服务端确定。Stripe 响应的 `pay_mode=redirect`，跳转 `payurl` 进入托管 Checkout；后台可选择 CNY、USD 或 HKD，按管理员设置的人民币/外币汇率自动换算。套餐 `stripe_quote`、下单响应及订单查询返回 `payment_currency`、`payment_amount_minor`、`payment_exchange_rate`；付款金额为对应币种的最小单位，钱包到账仍为 `credit_fen` 人民币分。订单固定报价不受后续汇率修改影响，历史空报价字段按 CNY 处理。支付后的浏览器返回参数不证明到账，需登录查询本人 `GET /api/billing/orders/{out_trade_no}` 的实际状态。Stripe 通知入口 `POST /api/billing/stripe/webhook` 不使用登录令牌，使用原始请求体及 `Stripe-Signature` 验签；部署与事件配置见 [Stripe Checkout](./BILLING.md#stripe-checkout)。

Stripe 配置通过管理端 **系统设置 → 支付计费 → Stripe 支付接入** 保存，对应管理员专用 `GET/PATCH /api/admin/settings/models` 的 `stripe_enabled`、`stripe_secret_key`、`stripe_webhook_secret`、`stripe_frontend_url`、`stripe_currency`、`stripe_usd_cny_rate`、`stripe_hkd_cny_rate`。汇率为 1 单位外币对应的人民币金额，返回精确十进制字符串；PATCH 接受字符串或数字，最多六位小数、必须为正数，空串清除；选择外币却未配置相应汇率时 Stripe 不开放。不自动拉取实时汇率。密钥加密入库，读取时返回空串和 `has_stripe_secret_key`、`has_stripe_webhook_secret` 标记，另返回配置就绪标记 `stripe_ready` 和根据 `public_base_url` 计算的 `stripe_webhook_url`；就绪不代表已完成商户联调。PATCH 省略或留空密钥保留旧值，`clear_stripe_secret_key=true`、`clear_stripe_webhook_secret=true` 明确清空，若同时提交非空新密钥则采用新值。保存后刷新当前服务的运行配置，无需重启后端；数据库设置（含明确清空）优先于可选环境变量初始值。

数字资产市场为可选模块。`GET /api/marketplace/capabilities` 可查询开关；市场关闭时其他市场业务接口返回 404。配置就绪状态不等于已完成真实存储或支付联调，详见 [MARKETPLACE.md](./MARKETPLACE.md)。

## 文档维护

- 路由维护中文 `summary`、`description` 和 `response_description`，描述实际权限、同步或异步行为、返回结果及关键错误。
- 请求和响应模型使用 `Field(description=...)` 说明含义、单位与空值行为，参数使用 `Query`、`Path`、`Header` 等声明说明。
- 通用中文分组、分页提示和 FastAPI 默认响应描述由 `backend/app/openapi_docs.py` 统一提供。
- 更新接口后直接重新生成 OpenAPI，不维护独立的静态接口清单；业务约束以实现和生成的模型为准。


Stripe 按语言报价：后台 stripe_currency=auto，stripe_usd_cny_rate 设置美元兑人民币汇率。GET /api/billing/skus 接受 language=zh|en（默认 zh）；POST /api/billing/orders 接受 language（同上），中文选择 CNY、英文选择 USD。返回 stripe_quote 与订单 payment_* 均为服务端固定报价。英文缺少汇率时不开放 Stripe，并返回 stripe_unavailable_reason="usd_rate_missing"；中文仍可用。后台 stripe_ready 要求两种语言均配置完整。
