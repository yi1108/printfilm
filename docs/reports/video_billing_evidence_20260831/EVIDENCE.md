# 视频计费异常证据包（2026-08-26 / 2026-08-27）

> **固定时间**：2026-08-31 从杭州线上 `8.136.41.61` Postgres 导出  
> **用途**：留存 8/26–8/27 费用异常根因、用户行为、原始数据，便于对内说明或复盘  
> **注意**：本目录不含部署密码；密钥仍在 `deploy/.env.secrets.local`（gitignore）

---

## 1. 数据来源

| 项 | 值 |
|----|-----|
| 主机 | `8.136.41.61`（杭州 ECS） |
| 数据库 | Docker `ai-movie-pg` / `printfilm` |
| 导出脚本 | `.tmp/export_video_billing_analysis.py` |
| 导出时间 | 2026-08-31 10:45 CST |
| 任务表 | `task_runs`（`fragment_video` 等视频类型） |
| 计费表 | `usage_events`（`billing_key` 含 `seedance`） |

**重要限制（历史数据）**：

- `usage_events.task_run_id` 多为空，**无法逐条对齐「哪条任务花了多少钱」**
- `task_runs.billing_charged_fen` 在 2026-08-31 计费模块上线前均为 0，**真实费用以 `usage_events.charge_fen` 为准**
- 日统计默认按 **UTC 日期**（与 `aug26_27_analysis.json` 一致）；北京时间 = UTC+8

---

## 2. 核心结论（两日合计）

| 日期 (UTC) | Seedance 调用 | 费用 (元) | 任务入队 |
|------------|---------------|-----------|----------|
| 2026-08-26 | 322 | 7,956.86 | 387 |
| 2026-08-27 | 473 | 13,352.26 | 1,354 |
| **合计** | **795** | **21,309.12** | **1,741** |

- **不是单价上涨**：单次约 ¥25–29（`seedance2:video0`）
- **是调用次数暴增**：8/25 仅 29 次 / ¥643 → 8/26 ×12 → 8/27 ×21
- **单用户集中**：`2929455133@qq.com` 两日约 ¥12,458（占 58%），均为 `fragment_video` 分镜视频

---

## 3. 用户 `2929455133@qq.com` 行为摘要

**任务类型**：仅 `fragment_video`（短剧分镜 → Seedance 出片）

| 日期 (UTC) | 任务 | 上游调用 | 费用 | 主要项目 |
|------------|------|----------|------|----------|
| 8/26 | 183 | 141 | ¥3,556 | P132 第1–3集、P131 第1集 |
| 8/27 | 1,014 | 306 | ¥8,903 | P132 多集批量 + P148 第1集 |

**项目**：

- **132** — 被裁员的躺平青年林发发（班味孢子丧尸 / 拼多多式系统）
- **148** — 被雷劈穿越的社畜许不得（抽象系统）
- **131** — 被裁打工人林发发（旧版同题材）

**典型操作**：

1. **8/27 UTC 05:00**（北京 13:00）：304 任务同时入队，多集批量「生成分镜视频」
2. **8/27 UTC 15:00**（北京 21:00）：新项目 148 第1集，73 次调用 / ¥2,145
3. **8/27 UTC 22:00**（北京次日 06:00）：323 任务再次批量入队（重试/补跑）

**失败仍可能已计费**：上游 Seedance 提交成功即记 `usage_events`，任务最终 `failed`/`cancelled` 不退费。

---

## 4. 本目录文件清单

| 文件 | 说明 |
|------|------|
| `EVIDENCE.md` | 本说明 |
| `MANIFEST.json` | 文件 SHA256 校验 |
| `aug26_27_analysis.json` | 8/26–27 专项统计 |
| `user_2929455133_aug26_27.json` | 重点用户任务/剧集/错误（含剧名） |
| `meta_export.json` | 导出元信息 |
| `video_billing_20260831_1044.xlsx` | Excel 全量（任务/用量/汇总/图表） |
| `video_tasks_20260831_1044.csv` | 视频任务 CSV |
| `video_usage_20260831_1044.csv` | 用量 CSV |
| `video_billing_analysis.html` | 交互报告（全量明细） |
| `aug26_27_cost_analysis.html` | 8/26–27 专项 HTML |
| `charts/` | 导出时生成的 PNG 图表 |

---

## 5. 复现方式

```bash
# 1. 确保 deploy/.env.secrets.local 已配置 DEPLOY_SSH_PASSWORD、DEPLOY_PG_PASSWORD
# 2. 重新导出（会写 .tmp/video_billing_report/）
python .tmp/export_video_billing_analysis.py

# 3. 专项分析
python .tmp/video_billing_report/analyze_aug26_27.py
python .tmp/video_billing_report/query_user_tasks.py   # 单用户剧集名

# 4. 固定证据到本目录
python docs/reports/video_billing_evidence_20260831/freeze_evidence.py
```

---

## 6. 凭据说明（不在此目录存放）

部署与数据库密码**仅**存在于本机：

```
deploy/.env.secrets.local   # 已 gitignore，勿提交
```

| 变量 | 用途 |
|------|------|
| `DEPLOY_SSH_PASSWORD` | 杭州 ECS `root@8.136.41.61` SSH |
| `DEPLOY_PG_PASSWORD` | 线上 Postgres（`docker exec ai-movie-pg psql ...`） |

在本机 PowerShell 查看（勿截图外发）：

```powershell
notepad deploy\.env.secrets.local
```

模板见 `deploy/.env.secrets.local.example`。
