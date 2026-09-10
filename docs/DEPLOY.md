# 线上发布流程（www.printfilm.com）

生产站点：**不是**把前端 dist 丢到 OSS 当「发布」。OSS 仅用于成片/分镜等媒体；站点由服务器 nginx + systemd 托管。

| 站点 | 地址 | 静态根目录 |
|------|------|------------|
| 用户前台（主） | https://www.printfilm.com/ 、 https://printfilm.com/ | `/opt/ai_movie/frontend/dist` |
| 用户前台（旧站保留） | https://kepu.printfilm.com/ | 同上 |
| 管理后台（主） | https://admin.printfilm.com/ | `/opt/ai_movie/admin/dist` |
| 管理后台（旧站保留） | https://admin.kepu.printfilm.com/ | 同上 |
| API | 同源 `/api` → `127.0.0.1:8000` | uvicorn `ai-movie-api` |

服务器路径约定：`/opt/ai_movie`。Postgres/Redis 走本机 Docker（端口 `15432` / `16379`，与旧 kepu 隔离）。发布验收 Host 用 **www / admin.printfilm.com**，勿再以 `kepu.printtfilm.com` 为主。

---

## 1. 发布前检查

1. 本地改动已提交（或明确要打进本次包的未提交文件）。
2. 确认 **不要**用 `deploy/scripts/upload_oss_web.py` 代替站点发布。
3. 生产前端构建必须 `VITE_API_BASE=`（空，同源）；禁止把本地 API 地址打进 dist。
4. Celery 需监听队列：`drama,oss,video,pipeline`（漫剧 LLM 独立 `drama` 队列，避免被科普成片 `pipeline` 堵住）。

---

## 2. 标准全量发布（推荐）

凭据与脚本在本机 **gitignore** 文件中：

```text
deploy/scripts/deploy_kepu.py
deploy/scripts/deploy_kepu_8136.py
deploy/.env.secrets.local
```

SSH / DB 密码**不要**写进脚本，放入 `deploy/.env.secrets.local`（可参考 `.env.secrets.local.example`）：

```text
DEPLOY_SSH_PASSWORD=…
DEPLOY_PG_PASSWORD=…
```

或发布前导出同名环境变量。

在仓库根目录执行：

```bash
# Windows
python deploy/scripts/deploy_kepu.py
```

脚本会：

1. **本地** `frontend` / `admin` 执行 `npm ci && npm run build`（`VITE_API_BASE=` 空，同源）
2. 打包源码 + 已构建的 `dist`（排除 `.venv` / `node_modules` / 生成媒体等）
3. SSH 上传并解压到 `/opt/ai_movie`（保留远端 venv）
4. 写入 compose env、`backend/.env`、systemd
5. **默认跳过** `docker compose`（不动 Postgres/Redis 容器）；仅 `SETUP_INFRA=1` 时才 up
6. 远端 `pip install -r requirements.txt`（**不再**在服务器 npm build）
7. 重启 `ai-movie-api`（worker 默认停用；任务在 API 进程内调度）
8. 健康检查：`/api/health`、前台与后台首页

**默认不改 nginx、不跑 certbot、不动容器**（线上 HTTPS / 库已配好即可）。仅在需要时再开：

```bash
# 重写宝塔 vhost（静态根 / 反代）；已有 Let's Encrypt 证书则自动开 443
set SETUP_NGINX=1
python deploy/scripts/deploy_kepu_8136.py

# 申请/续签证书 + 按证书写 443（可与 SETUP_NGINX 同开）
set SETUP_TLS=1
python deploy/scripts/deploy_kepu_8136.py

# 仅当要重建/启动 Postgres+Redis 容器时
set SETUP_INFRA=1
python deploy/scripts/deploy_kepu_8136.py
```

已构建过 dist、只想重传时可设 `SKIP_LOCAL_BUILD=1`（需本地 `frontend/dist` 与 `admin/dist` 已存在）。

`node_modules` 已存在时会**跳过 `npm ci`**（Windows 上 ci 常需 5–15 分钟）；需强制重装依赖时设 `FORCE_NPM_CI=1`。

跳过 apt 装包：`SKIP_BOOTSTRAP=1`。

**注意**：全量脚本会覆盖远端 `backend/.env` 为脚本内嵌模板。若线上临时改过密钥/回调，发布后核对 EPAY / CORS / OSS 等项。

---

## 3. 热修（小改动）

仅改后端个别文件时，可 SSH 上传文件后：

```bash
systemctl restart ai-movie-api.service
# 若改了 worker / celery 任务
systemctl restart ai-movie-worker.service
```

仅改前端时，在服务器：

```bash
cd /opt/ai_movie/frontend && npm ci && VITE_API_BASE= npm run build
# nginx 静态根已指向 dist，一般无需 reload
```

仅改 admin：

```bash
cd /opt/ai_movie/admin && npm ci && npm run build
```

模板封面 seed 若已上传 OSS，启动时勿反复同步上传（`seed_templates` 会跳过已有 https 封面），避免卡住 API 启动。

---

## 4. 服务与排障

| 单元 | 说明 |
|------|------|
| `ai-movie-api.service` | uvicorn `127.0.0.1:8000`（**建议 `--workers 1`**） |
| `ai-movie-worker.service` | celery `-Q drama,oss,video,pipeline`；unit 设 `PRINTFILM_DB_ROLE=celery` |
| `ai-movie-pg` / `ai-movie-redis` | Docker |

**Postgres 连接池**：生产 `.env` 使用 `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`（API）与 `DB_POOL_SIZE_CELERY` / `DB_MAX_OVERFLOW_CELERY`（Worker）。若 API 报 `sorry, too many clients already`，先看 `curl /api/health` 的 `db_pool`，再 `systemctl restart ai-movie-api ai-movie-worker`。

常用命令：

```bash
systemctl status ai-movie-api ai-movie-worker
journalctl -u ai-movie-api -n 80 --no-pager
curl -fsS http://127.0.0.1:8000/api/health
# 期望 task_runtime.healthy=true，且 scheduler/poller/watchdog 均为 running
curl -fsSI https://www.printfilm.com/ | head
curl -fsSI https://admin.printfilm.com/ | head
# 旧站保留（可选）
curl -fsSI https://kepu.printfilm.com/ | head
curl -fsSI https://admin.kepu.printfilm.com/ | head
```

**任务卡住排障**：health 里 `scheduler`/`watchdog` 非 `running`，或库中有到期 `pending` 但 `scheduler_running_jobs=0` 且持续数分钟 → 先看 journal 是否有 `restarting task scheduler` / `recovered orphaned`；看门狗应自动拉起，仍异常再 `systemctl restart ai-movie-api`。

API 起不来时优先看：启动 seed 是否卡在 OSS、双 worker `create_all` 竞态、`.env` 是否被覆盖。

---

## 5. 易支付（充值）注意

- `EPAY_PID` / `EPAY_KEY` 与开发环境一致即可（见本机 `backend/.env`，勿写入公开文档）。
- **`EPAY_NOTIFY_URL` 不能含 `/api/`**：`pay.gitcc.com` 防火墙会拦含 `/api/` 的回调 URL。
- 生产使用：`https://www.printfilm.com/epay/notify`（勿再写 kepu / printtfilm）
- nginx 将 `location = /epay/notify` 反代到 `http://127.0.0.1:8000/api/billing/epay/notify`

---

## 6. 发布后必须写记录

每次发布（全量或热修）在 [`docs/releases/`](./releases/) **追加一条**记录，并更新该目录索引。

模板与约定见 [releases/README.md](./releases/README.md)。
