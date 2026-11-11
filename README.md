# PRINTFILM

**Languages:** [中文](README.md) | [English](README_EN.md)

[![GitHub stars](https://img.shields.io/github/stars/yi1108/printfilm?style=social)](https://github.com/yi1108/printfilm)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **把故事做成能播的片子** — AI 漫剧与 AI 短视频，从文案到成片。

分步短视频创作：创作设置 → 文案与分镜 → 参考图生图 → 图生视频 → 合成预览。新建默认 AI 视频、3D 动画画风、9:16 竖屏、约 60 秒，也可选择静图成片，各阶段检查与编辑后再继续制作。

**源码**：[github.com/yi1108/printfilm](https://github.com/yi1108/printfilm) · **版本** 0.2.0

## 界面预览

**工作台**

![工作台](docs/images/image-20260910-home.png)

**AI 短视频** — 历史、分镜、成片

| 项目历史 | 分镜工作台 | 成片预览 |
|:---:|:---:|:---:|
| ![科普历史](docs/images/image-20260910-history.png) | ![分镜工作台](docs/images/image-20260910-studio.png) | ![成片预览](docs/images/image-20260910-preview.png) |

**AI 漫剧** — 项目、分集、剧本、分镜、资产

| 项目列表 | 分集工作台 | 剧本解析 |
|:---:|:---:|:---:|
| ![漫剧项目列表](docs/images/image-20260917-drama-list.png) | ![分集工作台](docs/images/image-20260917-drama-episode.png) | ![剧本解析](docs/images/image-20260917-drama-script.png) |

| 分镜编辑 | 资产库 | 管理后台 |
|:---:|:---:|:---:|
| ![分镜编辑](docs/images/image-20260917-drama-storyboard.png) | ![漫剧资产库](docs/images/image-20260917-drama-assets.png) | ![管理后台](docs/images/image-20260910-admin.png) |

## 核心功能

### 1. AI 漫剧

从一句话到分集成片，角色与场景可复用。

- 大纲 / 剧情摘要 / 剧本内容
- 资产库：角色、场景、道具
- 解析成镜后进入分镜编辑与画布
- 细则见 [docs/EPISODE_RULES.md](docs/EPISODE_RULES.md)

### 2. AI 短视频

在 `/history` 通过项目卡片管理短视频，点击新建进入 `/studio/new`。

- 精选四款非真人风格：3D 动画、二维动漫、绘本插画、国风水墨
- 输入想法生成文案，或粘贴已有文案；文案可编辑并保存草稿
- 确认文案后生成分镜，逐镜编辑旁白与画面；每镜使用固定画风参考图，并参考前镜图片延续角色与视觉风格
- AI 视频模式把每镜图片生成为带声音的镜头视频，支持单镜预览和重生；选择模型与清晰度后分阶段生成，再手动合成成片
- 静图模式生成图片和外部 TTS 配音，FFmpeg 添加图片运镜和字幕；两种模式都支持预览、下载
- 制作中可停止，失败时继续补齐缺失素材；离开页面后可回到项目恢复进度
- 旧对话项目在任务停止并结算后移交分步编辑，各历史版本保留原素材

### 3. 独立生成与短剧 Skills

图片、视频、音频提供独立生成入口；短剧创作技能见[短剧Skills](https://www.gitcc.com/ai1/film-skills)。

### 4. 管理后台

用户、订单、模板、任务中心和模型路由。

## 工作流程

```
选择画风、输入想法或已有文案
    → 编辑与保存文案 → 确认后生成分镜
    → 检查分镜卡片 → 使用画风参考图生成图片
    → AI 视频：图片生成镜头视频与声音 → 检查并合成
      静图成片：生成外部 TTS 配音 → 合成运镜、字幕与旁白
    → 预览与下载成片
```

每个阶段完成后停下来等待检查，下一步由用户明确启动。项目列表、分镜和素材均采用卡片展示。漫剧和工具中心沿用原有流程。

当前新建短片直接使用项目接口，旧对话会话的创建、消息及查询接口已移除，仅保留历史项目转入工作台的 `open-editor` 接口。历史任务恢复与项目交接仍依赖 `creation_sessions`、`creation_messages`、`creation_runs` 及项目会话字段；目标时长字段同时供当前流程使用。默认启动会自动处理结构；已有数据库设置 `DATABASE_BOOTSTRAP_ENABLED=false` 时，先在 `backend` 目录执行以下专用增量迁移，再重启后端。该命令只创建上述三张表、两个项目字段及索引，不执行种子数据，也不修改其他业务结构或已有数据；可重复运行。

```bash
python scripts/prepare_creation_schema.py
python scripts/prepare_creation_schema.py --check
```

Windows 可将 `python` 替换为 `.venv\Scripts\python.exe`；使用 `backend/.env` 的现有数据库配置。`--check` 只读检查，结构缺失时返回非零退出码。

## 技术特点

- **两条产品线共用一套生成能力** — 漫剧与短视频走同一上游
- **进程内任务平台** — scheduler / executor / poller，无需单独 Celery Worker
- **模型可换** — 管理后台配置 TokenFree Key 与模型，不必改代码
- **Docker 一键启动** — 公开镜像，拉取无需登录
- **可选计费** — 默认关闭；开启后按用量结算，见 [docs/BILLING.md](docs/BILLING.md)

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL · Redis |
| 前端 | React 19 · TypeScript · Vite 8（管理端 Tailwind + shadcn） |
| AI | TokenFree New API（文字 / 图 / 视频） |
| 部署 | Docker 全栈镜像，或本机三进程 + 中间件容器 |

## 快速开始（Docker 一键启动）

本机只需安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（或 Docker Engine + Compose）。镜像在阿里云 ACR `gcc` 公开命名空间，**拉取无需登录**。

### 1. 克隆并准备环境变量

```bash
git clone https://github.com/yi1108/printfilm.git
cd printfilm

cp deploy/.env.docker.example deploy/.env.docker
```

编辑 `deploy/.env.docker`，至少改这三项：

| 变量 | 说明 |
|------|------|
| `POSTGRES_PASSWORD` | 数据库密码（勿用示例默认值） |
| `SECRET_KEY` | 任意长随机串（会话 / 密钥加密） |
| `OPENAI_API_KEY` / `ARK_API_KEY` | TokenFree API Key（同一把填两处即可） |

无 Key 想先看界面：把 `ARK_MOCK=true`。

### 2. 一键启动

```bash
docker compose --env-file deploy/.env.docker up -d
```

等约半分钟（API 健康检查通过后，web / admin 才会起来）。

| 服务 | 地址 |
|------|------|
| 用户端 | http://localhost:8080 |
| 管理后台 | http://localhost:8081 |
| API / 文档 | http://localhost:8000 · `/docs` |
| 健康检查 | http://localhost:8000/api/health |

常用：

```bash
docker compose --env-file deploy/.env.docker ps          # 状态
docker compose --env-file deploy/.env.docker logs -f api # 看日志
docker compose --env-file deploy/.env.docker down        # 停止（保留数据卷）
```

### 3. 注册与管理员

| 角色 | 怎么拿 |
|------|--------|
| 普通用户 | 打开用户端 → `/auth` 邮箱注册 |
| 管理员 | 先用该邮箱注册 → 在 `.env.docker` 设 `ADMIN_BOOTSTRAP_EMAILS=你的邮箱` → `docker compose --env-file deploy/.env.docker up -d --force-recreate api`（**只提权，不造号**） |

仓库无内置演示账号；生产请立刻改掉密钥。

### 4. 更新到最新镜像

```bash
docker compose --env-file deploy/.env.docker pull
docker compose --env-file deploy/.env.docker up -d
```

### 5. 从源码构建（可选）

改过前后端代码，或拉不到 ACR 时：

```bash
docker compose --env-file deploy/.env.docker -f docker-compose.full.yml up -d --build
```

## 配置 TokenFree API Key

开源版文字 / 图 / 视频统一走 **TokenFree New API**（OpenAI 兼容：`https://www.tokenfree.com/v1`）。没有 Key 时只能 `ARK_MOCK=true` 看界面，不能真实生图 / 生视频。

### A. 在 TokenFree 拿到 Key

1. 打开 [https://www.tokenfree.com](https://www.tokenfree.com) 注册并登录。
2. 进入控制台的 **API 密钥 / Tokens**（部分部署路径为 `/token` 或 `/keys`）。
3. 点击 **创建**，填名称（如 `printfilm`），按需设额度 / 过期时间。
4. **立刻复制完整 Key**（形如 `sk-…`，只显示一次）。
5. 确认账户有余额或可用额度；模型列表里能看到你要用的对话 / 生图 / 视频模型。

> Key 等同密码，不要提交到 Git、不要发到群聊。泄露后在 TokenFree 控制台作废并重建。

### B. 写入 Docker 环境（推荐自托管首次启动）

编辑 `deploy/.env.docker`：

```env
OPENAI_API_KEY=sk-你的密钥
OPENAI_BASE_URL=https://www.tokenfree.com/v1
ARK_API_KEY=sk-你的密钥
ARK_MOCK=false
MODEL_LLM=kimi-k2.6
MODEL_IMAGE=seedream-5-0-pro
MODEL_VIDEO=seedance-2-5
```

`OPENAI_API_KEY` 与 `ARK_API_KEY` 填**同一把**即可。然后重建 API 容器使环境生效：

```bash
docker compose --env-file deploy/.env.docker up -d --force-recreate api
```

打开 http://localhost:8000/api/health ，`ark_mock` 应为 `false`。

### C. 在管理后台填写（推荐日常改 Key）

1. 用管理员登录 http://localhost:8081 。
2. 打开 **系统设置 → 模型**（路由 / TokenFree 渠道）。
3. 在 TokenFree 渠道填入 API Key 并保存。
4. 按需调整默认文字 / 图 / 视频模型；保存后即时生效，一般不必改 `.env`。

后台保存的 Key 会加密进数据库；换机器迁移时记得一并备份库，或重新在后台填写。

### D. 联调排查

| 现象 | 处理 |
|------|------|
| 生图 / 生视频报未配置 Key | 检查 `.env.docker` 是否仍为 `replace-me`，或后台渠道是否已填 Key |
| `ark_mock: true` | 关掉 `ARK_MOCK`，并确认 Key 非空后 `--force-recreate api` |
| 401 / 额度不足 | 到 TokenFree 控制台看 Key 是否启用、余额是否够 |
| 模型名 404 | 在后台模型列表里选 TokenFree 实际提供的模型 id |
## 适用场景

- 短视频 / 获客片：把卖点做成可投放的短片
- 漫剧 / 短剧：从大纲到分集，角色场景保持一致
- 单点出图出片：工具中心直接生成
- 自托管：Docker 拉镜像即可在自己的机器上跑

## 目录结构

```
backend/                  FastAPI、流水线、计费、任务运行时
frontend/                 用户端
admin/                    运营后台
deploy/                   环境变量示例、中间件 compose
docs/                     规范与专题文档
docker-compose.yml        拉公开镜像一键启动
docker-compose.full.yml   从源码构建
```

## 社区

- GitHub：https://github.com/yi1108/printfilm
- 微信加 **`gitcc188`**（备注「入群」）：部署答疑 / 短剧交流 / 模板分享

## Star History

[![Star History Chart](https://api.star-history.com/chart?repos=yi1108/printfilm&type=date&legend=top-left)](https://www.star-history.com/#yi1108/printfilm&Date)

## 更多文档

| 文档 | 内容 |
|------|------|
| [docs/STANDARDS.md](docs/STANDARDS.md) | 工程规范 |
| [docs/API.md](docs/API.md) | 中文 API 文档、认证与接口接入约定 |
| [docs/BILLING.md](docs/BILLING.md) | 计费与易支付 |
| [docs/EPISODE_RULES.md](docs/EPISODE_RULES.md) | 漫剧分集 |
| [docs/SEEDANCE_2_5.md](docs/SEEDANCE_2_5.md) | Seedance 参数 |
| [deploy/README.md](deploy/README.md) | 本机中间件与运维 |

## 贡献

欢迎 Issue / PR。提交前对照 [docs/STANDARDS.md](docs/STANDARDS.md)：简体中文文案、函数注释、服务端分页；勿提交 `.env`、密钥与生成媒体。

```bash
cd frontend && npm run lint
cd ../admin && npm run lint
cd ../backend && pytest
```

## 开源许可

本项目采用 [MIT License](LICENSE)。
