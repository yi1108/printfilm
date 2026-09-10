# Kepu batch — reference

## Endpoints（localhost on prod）

| Method | Path | 用途 |
|--------|------|------|
| POST | `/api/auth/login` | `{"email","password"}` → `access_token` |
| POST | `/api/projects` | 创建；`source_type=script` |
| PATCH | `/api/projects/{id}` | 补 `output_ratio` / `voice_id` / `pipeline_mode` |
| GET | `/api/projects/{id}` | 状态、`shots`、`source_text` |
| POST | `/api/projects/{id}/generate` | 首次→拆分镜；`SCRIPT_READY` 再调→成片 |
| POST | `/api/projects/{id}/cancel` | 取消进行中 |
| DELETE | `/api/projects/{id}` | 删除 |

Create body 关键字段：`template_id`, `title`, `source_type`, `source_text`, `resolution_mode`, `pipeline_mode`, `output_ratio`, `voice_id`。

## Status

`DRAFT` → `SCRIPTING` → `SCRIPT_READY` → `IMAGING` → `VIDEOING` / `AUDIOING` → `COMPOSING` → `DONE`  
失败/取消：`FAILED` / `CANCELLED`。忙碌态勿重复 generate。

## Templates（`backend/app/services/templates_seed.py`）

多样打散优先非重复；开源向优先 `opensource_live_work`（真人工作场景），也可混用：

`opensource_live_work`, `opensource_showcase`, `live_product_desk`, `live_street_interview`, `live_cinematic`, `live_person`, `photo_realism`, `portrait_story`, `film_cinematic`, `noir_thriller`, `vox_papercut`, `docu_warm`, `kids_flat`, `soft_anime`, `chalk_whiteboard`, `cyber_neon`, `epic_fantasy`, `magazine_collage`, `brand_clean`, `pixel_retro`, `retro_vhs`, `ink_guofeng`

## Voices（`backend/app/services/voices.py`）

| voice_id | 标签 |
|----------|------|
| `zh_female_cancan_uranus_bigtts` | 灿灿 · 女声旁白 |
| `zh_female_tianmeixiaoyuan_uranus_bigtts` | 甜美女声 · 故事 |
| `zh_female_shuangkuaisisi_uranus_bigtts` | 爽快女声 · 都市 |
| `zh_female_vv_uranus_bigtts` | Vivi · 国风女声 |
| `zh_male_shaonianzixin_uranus_bigtts` | 少年梓辛 · 男声 |

## scripts JSON 示例

```json
[
  {
    "repo": "https://www.gitcc.com/org/repo",
    "article": "https://mp.weixin.qq.com/s/xxxx",
    "template_id": "cyber_neon",
    "output_ratio": "16:9",
    "voice_id": "zh_male_shaonianzixin_uranus_bigtts",
    "pipeline_mode": "full",
    "title": "示例标题",
    "source_text": "第一段痛点。\n\n第二段能力（来自公众号）。\n\n第三段场景与开源价值。"
  }
]
```

## SSH 传输

中文 JSON **必须** base64 整文件写远端，例如：

```python
open("/tmp/scripts.json","wb").write(base64.b64decode(b64))
```

本地控制台乱码不代表库坏；以远端 `ascii(title)` 为准。

## 凭据

- Demo：`demo@example.com` / `demo1234`
- SSH：环境变量或 `deploy/scripts/deploy_kepu.py`（该文件已 gitignore）
- 公开站：`https://kepu.printfilm.com/studio/{id}`
