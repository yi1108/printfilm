# PRINTFILM 部署（Docker 只跑库与缓存）

> 开源仓库以根目录 [README.md](../README.md) 的 Docker 全栈为准。  
> 现网机器发布手册 `docs/DEPLOY.md`、发版记录 `docs/releases/` 仅本机保留，不上库。  
> 本文仅描述 Postgres/Redis compose 与本机跑 API 的补充说明。**不要**用 OSS 上传前端 dist 代替站点发布。

## 分工

| 组件 | 运行方式 |
|------|----------|
| PostgreSQL | Docker |
| Redis | Docker |
| FastAPI / 进程内任务平台 | 同一个宿主机 Python 进程 |
| 前端 / 管理后台 | 宿主机 `npm run build` + nginx 静态托管 |

## 1. 启动中间件（独立目录，不复用其它项目的库）

```bash
cp deploy/.env.prod.example deploy/.env.prod   # 改密码；默认端口 15432 / 16379
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.prod up -d
docker compose -f deploy/docker-compose.yml ps
```

容器名：`ai-movie-pg`、`ai-movie-redis`。与 kepu（5432/6379）隔离。

Postgres / Redis 端口均映射为 `0.0.0.0`（便于本机直连调试）。公网暴露有风险，仅受控调试时使用，并确认强密码与云安全组。常规发布默认**不**执行 `docker compose`（见 `SETUP_INFRA=1`）。

## 2. 配置应用

将 `deploy/.env.prod` 中的 `DATABASE_URL` / `REDIS_URL` / `ARK_*` 等写入 `backend/.env`（密码与 compose 一致）。

正式环境示例：

```env
DATABASE_URL=postgresql+asyncpg://printfilm:<密码>@127.0.0.1:5432/printfilm
DATABASE_URL_SYNC=postgresql+psycopg2://printfilm:<密码>@127.0.0.1:5432/printfilm
REDIS_URL=redis://127.0.0.1:6379/0
TASK_RUNTIME_MAX_CONCURRENCY=4
TASK_USER_MAX_CONCURRENCY=4
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=20
```

连接池按需建立连接，每个 API 进程最多使用 `50 + 20 = 70` 条；PostgreSQL `max_connections=100` 时保留 30 条给其他应用、迁移、调试和管理连接。增加进程或实例时，各自有独立连接池，须按所有进程的最大连接数之和重新核对数据库预算。修改连接池环境变量后，宿主服务重启 API；Docker 部署重建 API 容器以重新加载环境变量。连接池扩容仍需配合长任务在等待上游前释放数据库事务。

需本机已安装：Python 3.12、FFmpeg（PATH）、Node.js。

**中文字幕字体（必装）**：科普成片用 FFmpeg `drawtext` 烧录叠字/口播字幕。Ubuntu 示例：

```bash
sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei fontconfig
# 可选：写入 backend/.env
# FRAMECUT_FONT=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
```

缺字体时字幕会显示为「方框」（□），需装字体后**重新合成**该项目成片。

## 升级前必须检查数据库结构

2026-10-24 本地升级漏跑媒体计费迁移，分集列表因缺少 `task_runs.billing_snapshot` 返回 500。`DATABASE_BOOTSTRAP_ENABLED=false` 会跳过启动建表和补列；重启、未发布价格或健康检查成功都不能代替迁移。

升级现有数据库时，先备份目标库，再用新版本代码及目标环境的数据库配置执行：

```bash
cd backend
# 使用该环境的虚拟环境 Python；团队结构等其他迁移仍按对应发布说明执行。
python scripts/prepare_media_schema.py
python scripts/prepare_media_schema.py --check
```

两条命令都必须返回 0 才能重启 API 与任务执行节点。`--check` 在只读事务中校验媒体必需表、列和交付唯一索引，缺失时返回 1；发布脚本或 CI 必须传播该退出码并中止，不能忽略错误继续重启。迁移命令完成后也会校验结构，失败回滚。

重启后除 `/api/health` 外，还须以有权限的登录用户读取目标环境现有项目的分集列表和任务列表，确认返回 200。价格发布另行操作；先完成结构迁移，不要求自动启用新价格。详见 [媒体迁移与故障记录](../docs/MEDIA_MODEL_STRATEGIES.md#发布与兼容)。

## 3. 启动 API 与任务平台

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
# Linux:  source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

调度器、执行器、轮询器与看门狗随 API 启动，无需单独的 Celery worker。OSS 上传在后台协程执行。

## 4. 前端

```bash
cd frontend
npm install
npm run dev          # 开发
# npm run build && npx serve dist   # 简单静态托管
```

## 运维

```bash
# 看中间件日志
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.prod logs -f

# 停中间件（不删数据）
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.prod down

# 停并删卷（清库/清 Redis）
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.prod down -v
```

任务并发：通过 `backend/.env` 中的 `TASK_RUNTIME_MAX_CONCURRENCY`、`TASK_USER_MAX_CONCURRENCY` 调整统一任务平台并发。

测试环境由 Jenkins 轮询 **GitHub 仓库 `yi1108/printfilm` 的 `dev` 分支**自动发布；日常测试发版提交并推送代码即可，不需要手动上传补丁或更新服务器容器。推送前用 `git remote -v` 确认目标；`origin` 指向该 GitHub 仓库时执行 `git push origin dev`，若 `origin` 指向 GitCC，则还需推送到对应 GitHub remote（例如 `git push github dev`）。推送后核对 Jenkins 构建版本与运行中的镜像标签一致。

API 启动阶段会自动执行数字资产 App 的幂等增量结构迁移。迁移在 PostgreSQL advisory lock 内完成，覆盖内容、播放、点赞、收藏、评论、Apple、钱包、退款和收益表；只新增缺失表、列和索引，不删除或改写历史数据。迁移失败会使 API healthcheck 失败，发布不会继续启动 Web。Jenkins 不需要单独执行迁移命令。

```sh
docker compose -f docker-compose.full.yml --env-file deploy/.env.docker up -d --build
```

启动日志会记录结构迁移失败原因。`scripts.prepare_marketplace_app_schema` 仍保留用于离线核验和故障恢复，但不再是正常发布的必需手工步骤。统一钱包的余额数据迁移仍不在启动阶段执行。

本地 API 联调连接共享测试数据库时，设置 `TASK_RUNTIME_ENABLED=false`，只保留测试服务器执行调度、轮询和孤儿恢复。已由服务器初始化的共享数据库还可设 `DATABASE_BOOTSTRAP_ENABLED=false`，本机只读取模型缓存，不再重复建表、补列、seed 或提升管理员。本地仍能创建和查询任务，执行与产物存储由测试服务器负责；本地页面应能访问服务器返回的媒体地址。独立本地数据库或实际执行节点保持两个开关为 `true`（默认）。不要让多个调试实例同时恢复同一队列。

任务中心区分「待调度」（已到期）、「待激活」（尚无调度时间，可能等前置镜或额度）和「延时等待」。排查积压时一起查看调度最近成功时间、连续失败次数、数据库锁等待；增加并发无法解决调度停滞或锁等待。

## OSS（成片 / 分镜 / 前端）

在 `backend/.env` 开启：

```env
OSS_ENABLED=true
OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
OSS_BUCKET=your-bucket
OSS_FOLDER=kepu
OSS_ACCESS_KEY_ID=...
OSS_ACCESS_KEY_SECRET=...
```

- 分镜图/视频/配音/成片：本地落盘供 FFmpeg，上传后 DB 存 OSS 公网 URL（前端预览走 OSS）
- 对象前缀：`kepu/generated/p{id}/...`
- 前端构建产物上传：

```bash
cd frontend && npm run build
cd ../backend && .venv/bin/python ../deploy/scripts/upload_oss_web.py
# → https://{bucket}.oss-cn-beijing.aliyuncs.com/kepu/index.html
```
