# PRINTFILM 全局规范

本仓库（`ai_movie`）的统一工程约定。写代码、改文档、发版前先对照本文；专项细则见文末链接。

适用：`backend/`（FastAPI）、`frontend/`（用户端）、`admin/`（管理后台）、`deploy/`、`docs/`。

---

## 1. 总则

1. **说中文**：用户可见文案、提交说明、发布记录、产品文档默认简体中文。
2. **改动克制**：只改任务需要的文件；禁止顺手大重构、无关格式化、批量改无关注释。
3. **单一真相源**：业务状态以服务端/数据库为准；前端不做「假数据当真」的长期占位（临时 mock 须标清）。
4. **敏感信息不上库**：密钥、密码、`deploy_kepu.py`、真实 `.env`、token、`.tmp/` 抓取结果不得提交。
5. **先查再写**：新功能前先搜 `components/`、`lib/`、`services/`、`hooks/`，避免重复造轮子。

---

## 2. 注释规范

### 2.1 函数 / 组件 / Hook

每个函数（含导出组件、Hook）顶部必须有功能注释。

- 简单：单行 `//` 或 `#`
- 复杂：块注释 / JSDoc / docstring，说明用途、关键参数、返回值

```typescript
// 按状态 Tab 映射到后端 status 查询参数
function tabToStatus(tab: string): string {
  return TAB_STATUS[tab] || 'all'
}

/**
 * 打包选中成片为 zip 并触发浏览器下载。
 * @param ids 项目 id 列表（最多 50）
 */
async function packSelected(ids: number[]) {
  /* ... */
}
```

```python
# 将分镜旁白规范化为 Seedance 可用的制作约束块
def build_seedance_production_section(segment_script: str) -> str:
    ...
```

### 2.2 变量

每个变量都要有注释。连续声明可在顶部用一块注释统一说明：

```typescript
/*
 * page 当前页码
 * total 筛选后总数
 * typeMode 类型筛选（pipeline_mode）
 */
const [page, setPage] = useState(1)
const [total, setTotal] = useState(0)
const [typeMode, setTypeMode] = useState<'' | 'full' | 'image_text'>('')
```

---

## 3. 目录与分层

```
backend/app/
  api/           HTTP 路由（按域拆分；drama 在 api/drama/）
  services/      业务逻辑、流水线、方舟/OSS/计费
  models*.py     ORM
  schemas*.py    Pydantic 入出参
  workers/       Celery / autoscale
frontend/src/
  pages/         路由页（studio / drama / …）
  components/    可复用 UI
  api/           HTTP 客户端
  lib/           纯函数工具
  styles/        用户端全局样式（printfilm.css）
admin/src/
  pages/         运营页
  components/ui/ shadcn 组件
  api/           管理端请求
deploy/          compose、发布脚本说明
docs/            产品与工程文档（本规范所在处）
```

约束：

| 层 | 可以 | 不要 |
|----|------|------|
| `api/` | 鉴权、参数校验、调 service、组响应 | 堆长业务/直接拼方舟请求 |
| `services/` | 核心业务、外部 API、DB 编排 | 依赖具体 HTTP Request 对象做业务分支（除非必要） |
| `pages/` | 页面编排、本地 UI 状态 | 复制一整段 API 细节；应走 `api/` |
| 单文件 | 尽量 &lt; 500 行 | 继续膨胀；拆 `lib/` / 子组件 / service |

---

## 4. 前端规范

### 4.1 用户端 `frontend/`

- 样式以 **`styles/printfilm.css` + 语义化 class（`pf-*`）** 为主，与现有视觉体系统一。
- 路由与壳：`AppShell` / `SiteNav`；漫剧页 `active="drama"`。
- 请求统一走 `src/api.ts` / `src/api/*`；错误用可读中文抛给 UI。
- 列表筛选、分页：**服务端分页**（见历史页 `/api/projects`）；禁止只在前端 slice 全量列表当长期方案。
- 组件内临时 UI 状态用 `useState`；跨页共享若出现，优先评估提升到明确模块，避免隐式全局变量。

### 4.2 管理端 `admin/`

- **Tailwind + shadcn/ui**；用 `cn()` 合并 class。
- 复杂运营台布局可用 `admin-*.css` / `index.css` 中的语义 class（与用户端 `pf-*` 分离）。
- 分页组件复用 `PaginationBar`；列表接口带 `page` / `page_size` / `meta`。

### 4.3 交互与可访问性

- 按钮写清 `type="button"`（表单内防误提交）。
- 危险操作（删除、扣费）用确认对话框，文案说明后果。
- 加载 / 空态 / 错误三态都要有，禁止静默失败。

---

## 5. 后端规范

### 5.1 API

- 路径：`/api/...`；漫剧 `/api/drama/...`；管理 `/api/admin/...`。
- 鉴权：用户接口 `get_current_user`；管理 `get_current_admin`。
- 入参用 Pydantic；出参明确 `response_model`。
- 列表默认：**分页**（`page`、`page_size`、`meta.total`），并支持必要筛选参数。
- 错误：业务用 `HTTPException`，对外 `detail` 为中文短句；勿把堆栈直接回给前端。

### 5.2 异步与任务

- 长任务走 Celery（`pipeline` / `oss` 队列）；`USE_CELERY=true` 时本地也要起 worker。
- 启动 `seed_*` 不得阻塞过久：已有 OSS URL 勿重复同步上传。
- 多 worker 下注意 `create_all` / 迁移竞态；生产 API 建议单 worker 或显式迁移策略。

### 5.3 数据与媒体

- 成片/分镜先落本地供 FFmpeg，再按配置上传 OSS；DB 存可访问 URL。
- 删除项目时清理关联素材与 `works` 等从属数据（保持现有 delete 语义）。

### 5.4 计费 / 易支付

- SKU、扣费逻辑以 `services/billing.py` 为准。
- 生产 `EPAY_NOTIFY_URL` **禁止含 `/api/`**（易支付 WAF）；使用 `/epay/notify` + nginx 反代。详见 [BILLING.md](./BILLING.md)、[DEPLOY.md](./DEPLOY.md)。

---

## 6. Git 与协作

- 提交信息：说明**为什么**，1–2 句；不要纯堆文件列表。
- 不提交：`.env`、密钥、`deploy/scripts/deploy_kepu.py`、`frontend/dist`、`node_modules`、`.venv`。
- 大功能可拆 commit；与发布相关的文档（规范、发布记录）尽量同批可追溯。

---

## 7. 文档与发布

| 文档 | 何时更新 |
|------|----------|
| [PLACEHOLDER_BACKLOG.md](./PLACEHOLDER_BACKLOG.md) | 新增/下线 ComingSoon、disabled 入口 |
| [DEPLOY.md](./DEPLOY.md) | 发布方式、域名、回调、systemd 变更 |
| [releases/](./releases/) | **每次**线上全量或热修后追加一条 |
| [BILLING.md](./BILLING.md) | SKU、计费公式、支付配置变更 |
| **本文 STANDARDS.md** | 全局约定变更时 |

发布原则：

- 线上站点 = 机器 nginx + systemd，**不是**把 SPA 丢 OSS 当发布。
- 流程与检查清单见 [DEPLOY.md](./DEPLOY.md)。

---

## 8. 安全与配置

- 示例配置只放 `*.example`；真实值只在服务器 / 本机 `.env`。
- CORS 只放真实前台域名（主站 `www.printfilm.com` / `admin.printfilm.com`，旧站 `kepu.printfilm.com` / `admin.kepu.printfilm.com` 等）。
- 管理接口必须 `role=admin`；bootstrap 邮箱仅提升已有用户，不造号。

---

## 9. 自检清单（提 PR / 发版前）

- [ ] 新增函数/组件有顶部注释；成组 state 有块注释
- [ ] 文件未明显超过 500 行，或已拆分
- [ ] 列表接口带分页；筛选在服务端
- [ ] 无密钥、无本机绝对路径写入仓库
- [ ] 用户可见错误为中文
- [ ] 若动了占位入口 / 发布方式 / 计费，已更新对应 docs
- [ ] 若已上线，已写 [releases](./releases/) 记录

---

## 10. 相关文档

- [README.md](../README.md) — 仓库总览与本地启动  
- [DEPLOY.md](./DEPLOY.md) — 线上发布  
- [BILLING.md](./BILLING.md) — 计费  
- [PRINTFILM_UI_ROADMAP.md](./PRINTFILM_UI_ROADMAP.md) — UI 路由与视觉  
- [PLACEHOLDER_BACKLOG.md](./PLACEHOLDER_BACKLOG.md) — 占位功能表  
