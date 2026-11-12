# 测试环境自由画布入口修复（2026-11-12）

测试站点 `http://192.168.110.219:18080` 的 Jenkins 第 94 次发布使用提交 `78eccf0`，前端与 API 健康检查均正常，但 `/api/capabilities` 未返回 `printfilm_studio_enabled`。后端默认关闭该功能，前端入口守卫因此跳回 `/drama`。

测试容器 `printfilm-test-api-1` 使用 `/opt/printfilm-test/compose.yml`，从 `/opt/printfilm-test/app.env` 加载环境变量。确认没有运行中的 Agent、工作流及生成任务后，备份原环境文件，并持久写入 `PRINTFILM_STUDIO_ENABLED=true`，其他配置不变。

Jenkins `printfilm-test` 的 Smoke test 增加公开功能接口检查：必须返回 `printfilm_studio_enabled: true`，避免仅健康检查通过却缺失画布入口。

第 95 次构建成功，发布后 `/api/health` 返回 200，`/api/capabilities` 返回 `printfilm_studio_enabled: true`，前端静态资源返回 200。未调用付费生成，未更改用户画布内容或生产环境配置。
