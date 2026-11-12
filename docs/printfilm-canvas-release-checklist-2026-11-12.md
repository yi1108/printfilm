# 自由画布正式环境发版步骤

记录日期：2026-11-12。本文为待执行清单，**尚未发布正式环境**。正式执行以当时的 Jenkins 作业、镜像、Compose 配置和数据库为准，不直接套用旧版 systemd 发布脚本，也不复制测试数据库或整份环境文件。

## 1. 确定发布版本与备份

1. 确认本次正式发布的 Git SHA。测试第 95 次成功部署的是 `78eccf07cb0e6014ce9e71c018837b1d267877fc`；后来未提交的本地改动不属于该版本。若发布其他 SHA，应补做对应构建与回归。
2. 记录正式环境当前镜像标签、Compose 文件、环境文件、实际 Nginx 挂载文件及媒体卷。备份配置，记录上一成功版本。
3. 备份正式 PostgreSQL 数据库，并核验备份可读取；另行备份媒体目录。数据库导出不包含头像、图片、视频文件。
4. 检查 Agent、工作流和生成任务是否有在途任务，安排完成后切换。状态检查应覆盖 pending、leased、running、awaiting_poll、awaiting_review、cancel_requested 等实际运行状态。
5. 迁移期间暂停画布写入，备份及 JSONL 报告放在**非公开、持久化目录**，不能放在 `/static/generated` 下。设置文件权限并保存到容器之外。

## 2. 环境开关与数据库结构

在正式 API 实际加载的环境文件中设置：

```env
PRINTFILM_STUDIO_ENABLED=true
```

修改 env 文件后要通过发布流程重新创建 API 容器；仅 `docker restart` 不会重新读取 Compose 的 env_file。

结构迁移必须使用**本次新镜像/新代码 + 正式环境配置**。以下 Python 命令在 backend 工作目录执行；Docker 场景通过正式 Compose 的受控 one-off 容器执行，不在本机默认数据库上运行。

```bash
python scripts/prepare_media_schema.py
python scripts/prepare_media_schema.py --check
```

`DATABASE_BOOTSTRAP_ENABLED=false` 时不会自动创建画布表，需要显式执行现有的增量结构函数：

```bash
python - <<'PY'
import asyncio
from app.database import engine
from app.printfilm_studio.schema import apply_printfilm_studio_schema_patches

async def main():
    try:
        async with engine.begin() as conn:
            await apply_printfilm_studio_schema_patches(conn)
    finally:
        await engine.dispose()

asyncio.run(main())
PY
python scripts/migrate_project_canvas_sharing.py --check
```

先确认画布文档、Agent 会话/消息/运行/事件、工作流、配方、成员与邀请表齐全，再迁移数据。健康接口成功不能替代结构核验。

本版本停用旧组织团队。先只读检查，存在旧团队项目时按[项目团队说明](printfilm-project-teams-2026-11-09.md)完成迁移：

```bash
python scripts/migrate_retired_project_teams.py
# 目标库确认、备份完成且旧团队无活动任务后执行
python scripts/migrate_retired_project_teams.py --apply
```

此步骤解除旧项目团队字段并保留来源 ID，不迁移钱包资金。不得顺带开启统一钱包、重置历史结算或对历史零扣费任务补扣。

## 3. 旧画布数据迁移：独立于建表的必做步骤

新页面读取 `printfilm_studio_canvas_documents`；旧数据仍在 `drama_projects.content.canvas_nodes/canvas_edges`。仅发布代码、开启开关或建表，不会复制旧画布数据。

先预览：

```bash
python scripts/migrate_legacy_canvas.py --all
python scripts/migrate_legacy_canvas.py --all --repair-legacy
```

逐项审阅预览：`ready` 可迁移；`already_migrated`、`skipped_nonempty_target` 应保留；`invalid_source` 需查明原因。已验证的修复只处理重复节点 ID 和确认已删除的资产引用，不猜测跨项目资产、缺失媒体或未知节点类型。

预览通过后，为当次发布设置唯一的持久备份目录，再执行：

```bash
# 按正式容器实际挂载路径填写，不照抄测试容器目录
CANVAS_BACKUP_DIR=/persistent-private-backups/canvas-release-YYYYMMDD-HHMMSS
python scripts/migrate_legacy_canvas.py --all --repair-legacy --apply \
  --backup-dir "$CANVAS_BACKUP_DIR" \
  --report "$CANVAS_BACKUP_DIR/applied.jsonl"
python scripts/migrate_legacy_canvas.py --verify-backups "$CANVAS_BACKUP_DIR" \
  --report "$CANVAS_BACKUP_DIR/verified.jsonl"
python scripts/migrate_legacy_canvas.py --all --repair-legacy
```

所有退出码必须检查。最后一次只读预览应显示已迁移或按规则跳过，不应留下待迁移/异常项目而宣称全部完成。每个迁移项目应验证旧数据和资产未变、新画布哈希与版本符合备份。若用户已开始编辑导致校验不匹配，先核对新增修改，不覆盖用户内容。

迁移逻辑有项目锁和版本校验，按项目独立事务，可重复执行；原始旧数据保留。详见[迁移操作与修复规则](legacy-canvas-migration-2026-11-11.md)。

## 4. Nginx 与媒体文件

检查**实际生效的 Nginx 配置及其 bind mount 源文件**。容器挂载旧配置会覆盖新镜像自带的 `frontend/nginx.conf`，更新镜像并不能解决。

外层 HTTPS 代理和内层 Web 容器都必须保留 WebSocket Upgrade。画布协作路径是 `/api/printfilm-studio/projects/<项目ID>/presence`，以仓库 `frontend/nginx.conf` 中的专用 location 为准，调整为正式 API upstream，保留正式 TLS、域名与其他业务路由：

```nginx
location ~ ^/api/printfilm-studio/projects/[0-9]+/presence$ {
    proxy_pass http://FORMAL_API_UPSTREAM:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 75s;
    proxy_send_timeout 75s;
    proxy_buffering off;
}
```

写入前备份；执行 `nginx -t` 成功后才 reload。账号令牌通过 WebSocket 首帧发送，不放到 URL。

确认 `/static/` 转发以及 `/app/static/generated` 的持久挂载。抽查头像、旧画布本地媒体、OSS 媒体。头像丢失时从核对过账号身份的原始文件恢复，不能把另一环境相同数字用户 ID 的文件直接覆盖过来；不使用占位图片冒充恢复。已有正式媒体应保留，不用测试目录覆盖。

## 5. 发布后验收与 Jenkins 门禁

- `/api/health` 返回 200，运行时健康。
- `/api/capabilities` 必须返回 `printfilm_studio_enabled: true`；测试 Jenkins 已加入此检查，正式作业也要加入。
- 已登录用户能进入 `/canvas`，打开正式环境已有旧项目，节点、连线、布局和媒体均可见；修改后保存、刷新正常。
- 项目资产、任务列表、钱包接口返回正常，未因遗漏结构迁移或资金开关返回 500/503。
- 使用实际项目测试 `wss://正式域名/api/printfilm-studio/projects/<ID>/presence`。握手 101 证明代理畅通；未认证连接按预期关闭 4401，只是代理/鉴权基础检查，不能代替两个已登录会话的协作验收。
- 头像与代表性旧媒体 HTTP 200；无持续 404 或 WebSocket 重连报错。
- “运行到这里”的独立分支并发、下游依赖等待沿用已测实现。付费生成验收按当次明确的测试范围执行，不自动对历史节点批量生成。
- 保存发布 SHA、Jenkins 构建号、迁移计数、校验报告路径和实际验收结果。不能只凭构建 SUCCESS 宣布业务验收完成。

## 6. 回滚

1. 回退到记录的上一镜像与 Nginx 配置，`nginx -t` 后 reload；功能开关回退也需重新创建 API 容器。
2. 不删除新增表，不清空画布，不自动全库恢复以覆盖发布后的用户数据。
3. 单个新画布需撤销迁移时，脚本仅在目标未被后续编辑时允许恢复，并递增版本：

```bash
python scripts/migrate_legacy_canvas.py --restore /private-backups/project-XXX.json --apply
```

4. 若需要撤销旧团队归属迁移，按发布前数据库备份及实际新增修改单独制定恢复方案；镜像回退并不自动还原团队字段。历史账务、任务和媒体保持保留。

## 7. 本次测试环境已完成的实际验证

- 第 94 次发布代码正确，但遗漏功能开关；第 95 次发布后开关和健康检查通过。
- 后续发现挂载的旧 Nginx 文件缺少 presence location，已备份补齐、语法检查并热重载。实际 WebSocket 握手成功，无令牌连接按预期关闭 4401；未把该结果写成已登录协作验收通过。
- 严格预览：364 个 ready、18 个异常；启用已验证修复规则后 382 个 ready、27 项修复记录、0 个异常。
- 实际迁移 382 个项目、2,933 个节点；382 份备份核验全部通过，旧数据与资产记录未变。项目 369 恢复 5 个节点、1 条连线，版本 4 → 5。
- 测试迁移备份与报告：API 私有持久卷内 `/app/var/wallet-backups/legacy-canvas-20261112/`。正式环境选择自己的明确私有备份挂载，不依赖该测试路径。
- 用户 1 的账号身份摘要和头像路径与本地原始文件来源核对一致后，恢复缺失头像。原报错 URL 返回 200，文件 SHA-256 与原文件一致。
- 正式环境尚未执行上述步骤；没有为本次修复调用付费生成。
