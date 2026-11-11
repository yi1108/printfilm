# Printfilm Studio 工作流缺失表修复

日期：2026-11-06。

## 现象与根因

项目 430 的 `/api/printfilm-studio/projects/430/workflow` 持续返回 500，`PUT /api/printfilm-studio/projects/430/canvas` 保存也返回 500。

后端日志共同指向：`relation "printfilm_studio_workflow_runs" does not exist`。工作流状态接口直接查询该表，画布保存前的后台运行锁也会查询该表。模型已经存在，但 additive schema patch 没有把 `PrintfilmStudioWorkflowRun` 纳入建表清单；当前部署又设置了 `DATABASE_BOOTSTRAP_ENABLED=false`，不会通过启动 `create_all` 自动补表。

## 修复

- `apply_printfilm_studio_schema_patches()` 的 ORM 建表清单新增 `PrintfilmStudioWorkflowRun`。
- 补丁入口显式注册 `users`、`drama_projects`、`teams` 的 ORM 元数据，允许部署脚本独立执行，不再依赖调用方提前导入模型。
- 已对当前数据库执行 additive patch，只使用 `CREATE TABLE IF NOT EXISTS` 和既有索引/表创建逻辑，没有清空或迁移画布数据。
- 新增 `test_printfilm_studio_schema.py`，防止工作流表再次漏出部署补丁。

## 验证

- 两个 GET 接口使用项目所有者本地测试令牌均返回 200。
- 画布保存在外层事务最终回滚的情况下执行成功，没有持久改变项目 430 的版本。
- 独立 schema patch 执行成功。
- schema、画布持久化与故事工作流定向回归：10 passed。
- 运行日志随后已出现 `GET /workflow` 200 和 `PUT /canvas` 200。

全量 Printfilm Studio 回归另有 4 failed、8 errors，分别位于文本计费测试夹具、故事提示词优先级和工作流测试 mock 等其他开发中路径；本次未修改这些业务逻辑，不将全量套件记为全部通过。

## 后续部署

启用数据库 bootstrap 时，现有启动补丁会创建该表。关闭 bootstrap 时，发布前必须在目标库执行同一 additive schema patch，不能只重启进程或用 `/api/health` 代替结构检查。执行前应备份目标库，并在执行后使用已登录的项目工作流读取和画布保存请求做冒烟。
