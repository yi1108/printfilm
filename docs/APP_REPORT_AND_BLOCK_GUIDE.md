# App 视频举报与拉黑创作者联调文档

适用 iOS / Android，接口前缀为 `/api/marketplace/app/v1`。举报复用 Web 举报记录、私有证据及后台处置；拉黑复用现有账号级作者屏蔽记录，无需新建第二套表。

## 通用约定

- 全部接口需要 `Authorization: Bearer <token>`，游客先登录；凭证无效或过期返回401。
- JSON请求使用 `Content-Type: application/json`；可传 `Accept-Language: zh-CN` 或 `en-US`。用户填写的举报内容不翻译。
- 时间为北京时间（UTC+8）`YYYY-MM-DD HH:mm:ss`，不要再加8小时。
- 创作者编号取内容详情的 `creator.id`；举报目标取 `content_id`，不能传 `publication_id`。
- 拉黑不是平台封禁，不删除作品、不退款、不撤销已购权益，也不是双向账号封锁。

## 1. 举报视频

```http
POST /api/marketplace/app/v1/reports
Authorization: Bearer <token>
Content-Type: application/json
Accept-Language: zh-CN

{
  "target_type": "work",
  "target_id": 101,
  "statement": "该作品疑似未经授权使用本人视频，请平台核查。",
  "contact": "reporter@example.com",
  "evidence_ids": []
}
```

单视频 `target_type=work`，短剧分集 `target_type=series_episode`。不接受 `episode` 或整部系列。`target_id` 为原作品或分集编号。

`statement` 必填，10～5000字；`contact` 必填，1～200字；`evidence_ids` 可省略，最多10个本人已上传且就绪的图片或文档资产ID，不接收URL。目标访问权限、证据类型及所有权使用现有Web校验。

成功响应：

```json
{"id":123}
```

HTTP 200代表已受理，进入现有市场举报后台，不代表认定违规。联系方式、证据不公开给被举报者。无效字段返回422；不存在、不可访问或证据无权使用时，按Web业务校验返回错误。保留用户输入并显示服务端安全提示，不把所有失败都显示为“举报成功”。

当前没有举报请求幂等键。提交时禁用按钮，成功关闭表单；超时后不要自动重发，以免重复创建举报。建议先举报成功再询问是否拉黑，避免先拉黑导致当前目标无法访问。

## 2. 拉黑创作者

```http
PUT /api/marketplace/app/v1/me/author-blocks/12
Authorization: Bearer <token>
Accept-Language: zh-CN
```

无需请求体，12为 `creator.id`。成功响应：

```json
{"blocked":true}
```

重复提交幂等。自己或不存在的账号返回400：

```json
{"detail":{"code":"MARKETPLACE_AUTHOR_INVALID","message":"作者不存在或不能屏蔽自己。"}}
```

拉黑后当前账号的App内容流不再展示该作者的单视频、系列；公开详情、分集目录和当前版本播放等沿用同一可见性检查。游客请求不关联账号拉黑记录，因此登录内容请求必须携带Bearer。

已购记录仍保留，可通过已购详情和 `publication_id` 播放购买版本，仍须满足版权、封禁等限制。已有播放会话不承诺立即终止。本能力不增加评论用户过滤、互相禁止回复或站外屏蔽。

App收到成功后移除当前推荐列表中该作者内容，清空内容流游标并重新加载第一页。网络失败不要提前移除或永久缓存成功状态。

## 3. 取消拉黑

```http
DELETE /api/marketplace/app/v1/me/author-blocks/12
Authorization: Bearer <token>
```

成功响应：

```json
{"blocked":false}
```

无需请求体，重复取消仍成功。只操作当前用户自己的关系。取消后刷新拉黑列表和内容流，作者内容是否出现仍取决于审核、上架、版权及原有筛选条件。

## 4. 拉黑列表

```http
GET /api/marketplace/app/v1/me/author-blocks?page=1&page_size=20
Authorization: Bearer <token>
```

```json
{
  "items":[{"author_id":12,"author":"创作者名称","created_at":"2026-11-09 15:00:00"}],
  "meta":{"page":1,"page_size":20,"total":1}
}
```

`page` 从1开始，`page_size` 为1～50，默认20，最近拉黑优先；这里使用页码，不使用feed游标。`author` 是当前名称，可能为空，客户端可显示“创作者 / Creator”。列表未提供头像字段，不要将名称当作账号ID。

## 联调清单

- 游客操作先登录；登录后两台设备读取同一账号拉黑列表。
- 单视频、分集举报均进入现有举报后台；无权使用的证据被拒绝。
- 举报失败保留输入；举报成功再拉黑；重复点击不误创建多条举报。
- 重复拉黑、取消拉黑均幂等；不能拉黑自己或不存在账号。
- 拉黑后携带Bearer刷新内容流，作者单视频及系列消失；取消后按原可见性恢复。
- 已购记录不丢失，按publication_id播放仍执行原权益限制。
- 拉黑列表分页、空态、名称回退、北京时间及401重新登录正常。

配套请求见 [HTTP示例](examples/app-report-and-block.http)，完整契约见 [OpenAPI](openapi/marketplace-app-v1.json)。本仓库不含iOS工程，客户端菜单、确认弹窗与拉黑列表由App团队接入。
