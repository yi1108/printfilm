---
name: kepu-batch-opensource
description: >-
  Batch create PRINTFILM/kepu open-source科普 videos from WeChat articles + GitCC
  repos: scrape 公众号正文, write source_type=script口播 (no URLs), diversify
  template/ratio/voice, SSH-submit to prod, confirm storyboards, continue full
  pipeline. Use when user asks to 批量提交开源项目、抓公众号生成口播、确认分镜开始生成、
  kepu.printfilm.com demo 批量任务, or redo bad source_text from article text.
---

# Kepu 开源科普批量成片

线上：`https://kepu.printfilm.com/` · 账号：`demo@example.com` / `demo1234`  
API 变更优先走 **SSH → 服务器 `http://127.0.0.1:8000`**（外网 SSL 常不稳定）。

工作目录约定：本地产物放 `.tmp/`（已 gitignore），勿提交 token / JSON / 日志。

## 何时用

- 用户给出一批「标题 + GitCC + 可选公众号链接」要做成片
- 要求「先抓公众号再写 source_text」或纠正错误口播后重提
- 「确认所有分镜 / 继续生成」整批续跑

## 流程清单

```
Task Progress:
- [ ] 1. 解析清单（repo / article / 约束）
- [ ] 2. 浏览器抓公众号正文（必做；删文则 GitCC README）
- [ ] 3. 写 .tmp/scripts_YYYYMMDD.json（script + 多样性）
- [ ] 4. base64 SSH 上传并创建+首次 generate（到 SCRIPT_READY）
- [ ] 5. ascii() 校验标题/口播 UTF-8
- [ ] 6. SCRIPT_READY 后二次 generate（成片）
- [ ] 7. 汇报 studio 链接表
```

### 1. 解析清单

每条至少：`title_hint`、`repo`、可选 `article`（mp.weixin.qq.com）。  
默认：`source_type=script`、`pipeline_mode=full`、`resolution_mode=preview`。  
用户指定「只到分镜」则停在步骤 4，勿执行步骤 6。

### 2. 抓公众号（硬约束）

1. 用 **cursor-ide-browser**：`browser_navigate` → `browser_lock` → 等正文 → CDP `document.body.innerText` 或 snapshot。
2. 写入 `.tmp/wechat-YYYYMMDD.md`（标题、要点、功能、场景）。
3. **禁止**仅凭标题/简介编功能细节当正文。
4. 公众号「已删除」→ 抓 GitCC README（公开页）；仍无文则标 `source=user_brief`，口播只展开用户原句，并在汇报里标明。
5. 私仓需登录时不要硬登；改用用户文案或请用户补链接。

### 3. 写口播 JSON

路径：`.tmp/scripts_YYYYMMDD.json`，UTF-8 数组。字段：

| 字段 | 说明 |
|------|------|
| `title` | 中文短标题 |
| `source_text` | 完整口播，3 段左右，**禁止** URL / 域名 / 端口 / `http` |
| `template_id` | 每条尽量不同，见 [reference.md](reference.md) |
| `output_ratio` | 在 `16:9` / `9:16` 间打散 |
| `voice_id` | 在 5 个 openspeech 音色间打散 |
| `pipeline_mode` | 默认 `full` |
| `repo` / `article` | 溯源用，不进口播 |

口播结构：痛点/风口 → 核心能力（来自正文）→ 场景与开源价值。

### 4. 提交（拆分镜）

```bash
python .cursor/skills/kepu-batch-opensource/scripts/batch_submit.py .tmp/scripts_YYYYMMDD.json
```

脚本会：读 SSH 凭据（见下）→ base64 上传 JSON → demo 登录 → `POST /api/projects` → `POST .../generate` → 写 `.tmp/submit-results.json`。

凭据（勿写入 skill / 勿提交）：

1. 环境变量 `KEPU_SSH_HOST` / `KEPU_SSH_USER` / `KEPU_SSH_PASSWORD`
2. 或已 gitignore 的 `deploy/scripts/deploy_kepu.py` 中 `HOST`/`USER`/`PASSWORD`

### 5. UTF-8 校验

在服务器对新建 project：`ascii(title)` + `source_text[:20]`。乱码则 cancel+delete 后用 base64 重传，勿用可能损坏编码的 scp/echo。

### 6. 确认分镜并成片

分镜齐后（`SCRIPT_READY` 且 `shots>0`）：

```bash
python .cursor/skills/kepu-batch-opensource/scripts/batch_confirm_continue.py --ids 49-58
# 或 --from-results .tmp/submit-results.json
```

等价 API：对每个 `SCRIPT_READY` 再 `POST /api/projects/{id}/generate` → 进入 `IMAGING`…  
进行中（`SCRIPTING`/`IMAGING`/…）勿重复点，会 409。

重做整批：先 `POST .../cancel`（可忽略失败）再 `DELETE`，再提交。

### 7. 汇报

表格：`# | id | title | template | ratio | voice | shots | status | studio URL`。  
注明哪些口播来自公众号 / README / 用户简介。

## 运维注意

- 生产前端构建：`VITE_API_BASE` 必须为空（同源），禁止把本地 `.env` 打进 dist。
- Celery 需听 `-Q pipeline,oss`（异步 OSS 上传）。
- 勿 commit `.tmp/`、token、含密码的 deploy 脚本。

## 详细参考

- 模板 / 音色 / API / 状态机：[reference.md](reference.md)
