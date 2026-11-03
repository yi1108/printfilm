# 数字资产市场中英文接入与部署

市场用户页面、创作流程中的市场入口和 App v1 共用 `zh` / `en`。管理后台继续中文操作，分类和客服配置支持双语。用户填写的标题、简介、标签、审核理由不自动翻译；人民币金额仍为整数分。

## 接口契约

请求携带 `Accept-Language: en-US` 或 `zh-CN`，支持语言优先级 q 值。未指定或无法匹配时使用中文。市场 JSON 返回 `Content-Language: en` / `zh-CN` 和 `Vary: Accept-Language`。调用方缓存必须区分语言；鉴权内容仍须区分用户。

```http
GET /api/marketplace/app/v1/categories
Accept-Language: en-US

GET /api/marketplace/app/v1/feed?content_type=all&category_code=short_film&limit=20
Accept-Language: en-US
```

分类响应保留 `version`、`names`，新增 `items`：`code`、`name_zh`、`name_en`、`enabled`、`label`、`translation_missing`。公开接口只返回启用分类；管理接口保留停用分类。数组顺序即展示顺序。

内容增加 `category_code`、`category_label`、`category_labels`。原 `category` 保留历史中文值。筛选优先使用 `category_code`；旧 `category` 参数仍支持历史中文名称和改名前别名。单视频、系列、招募草稿支持只传 `category_code`，同时传旧字段时代码优先。

固定业务代码保持不变：

- `content_type`: `work` / `series` / `series_episode`。
- `sale_type`: `free` / `copyright_contact` / `platform_unlock`。
- `access_mode`: `free` / `preview` / `entitled`。
- 审核、媒体和播放状态保持原枚举。

App 用代码判断逻辑，显示使用 `content_type_label`、`sale_type_label`、`access_mode_label`、`audit_status_label`、`media_status_label`、`preview_status_label`、`playback_status_label`。字段存在时才添加对应标签。金额、发布版本、签名链接用途、权益与支付回调语义不变。原片、试看及 HLS 权限仍按原规则执行。

错误保留旧 `detail` 结构和 HTTP 状态，增加 `error: {code, message, params}`。既有业务码原样保留；原来只有文字的已登记错误使用模板固定编号。客户端以 code 判断业务，显示当前语言 message；不要解析中文或英文提示来判断余额、付款或权益状态。验证错误仍保留 `loc`、`type` 和限制参数。

新通知保存 `template_code`、`message_params` 和原始文字；查询按当前语言渲染，并返回 `original_message`。历史无模板通知 `historical=true`，保留原文。人工审核理由不翻译。客服的微信、二维码、业务编号共用，`name_en` / `hours_en` 缺失时保留中文值。

## 授权函

`GET /api/marketplace/authorization` 的 `template` 始终为中文签署原文；新增 `reading_reference` 为匹配当前协议版本的完整英文阅读对照。英文阅读不参与签署正文、哈希、PDF 和授权有效性计算，也不会触发重签。未知版本不套用其他版本译文。签署接口保持原有参数与确认条件。

## 显式增量迁移

先备份数据库，停写市场分类和内容，再在 backend 目录执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_marketplace_locale_schema
.\.venv\Scripts\python.exe -m scripts.prepare_marketplace_locale_schema --apply --backup-file C:\backups\before-marketplace-locale.dump
.\.venv\Scripts\python.exe -m scripts.prepare_marketplace_locale_schema --check
```

默认命令只读检查分类与计数。`--apply` 要求已存在的非空备份文件；备份有效性应由部署方验证。迁移增加双语列、分类索引、历史名称映射，回填 Work / Series / Recruit 的分类代码。已移除但仍被使用的类别保留为停用分类；自定义历史分类没有英文时不猜测翻译，在后台补齐。可重复运行，不修改标题、内容版本、审核、已购发布快照或签署原件。

本地数据库已先完成 pg_dump 备份及归档可读性检查，再执行迁移。其他环境必须各自备份、迁移及 `--check` 后重启后端，再更新两个前端；不能只部署代码而遗漏结构。

## 维护与回归

前端静态词典为 `frontend/src/features/marketplace/locale-text-*.ts`。后端可读错误词典为 `backend/app/marketplace/locale_messages.json`。更新后端词典后运行 `node scripts/sync_marketplace_locale.mjs` 同步前端已收到提示的重绘词典；不调用翻译服务。

更改语言不重新挂载编辑器、不重建上传任务和签名画布。公开列表重取只读数据时用请求生命周期标记排除旧响应。历史自定义分类和人工内容仍可能显示中文，这是保留原文的约定。

自动化覆盖：语言协商与并发隔离、字段/价格/版本不变、类别代码优先/改名/停用/旧名称、新通知与人工理由、授权中文原件不变、App 分类和播放模式。仍应在每个实际部署环境检查移动端长文案、真实 OSS 媒体和 App 缓存语言键；本次不代表重新验收 Apple 实际支付或真实转码链路。
