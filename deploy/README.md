# PRINTFILM 部署（Docker 只跑库与缓存）

> **生产站点发布（www.printfilm.com / admin.printfilm.com；kepu 旧站保留）** 请以 [docs/DEPLOY.md](../docs/DEPLOY.md) 为准；每次发布写 [docs/releases/](../docs/releases/)。  
> 本文仅描述 Postgres/Redis compose 与本机跑 API 的补充说明。**不要**用 OSS 上传前端 dist 代替机器发布。  
> 杭州全量脚本：`deploy/scripts/deploy_kepu_8136.py`。默认**不**改 nginx / **不**跑 certbot / **不**动 Postgres·Redis 容器；改站点设 `SETUP_NGINX=1`，签证书设 `SETUP_TLS=1`，重建中间件设 `SETUP_INFRA=1`。验收 Host 用 **www.printfilm.com**。

## 分工

| 组件 | 运行方式 |
|------|----------|
| PostgreSQL | Docker |
| Redis | Docker |
| FastAPI / Celery worker | 宿主机 Python 进程 |
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
USE_CELERY=true
```

需本机已安装：Python 3.12、FFmpeg（PATH）、Node.js。

**中文字幕字体（必装）**：科普成片用 FFmpeg `drawtext` 烧录叠字/口播字幕。Ubuntu 示例：

```bash
sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei fontconfig
# 可选：写入 backend/.env
# FRAMECUT_FONT=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
```

缺字体时字幕会显示为「方框」（□），需装字体后**重新合成**该项目成片。

## 3. 启动 API + Worker

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
# Linux:  source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

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
