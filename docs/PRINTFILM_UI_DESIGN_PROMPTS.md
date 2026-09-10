# PRINTFILM 多产品平台 UI 设计提示词

面向 Midjourney / GPT Image / Figma AI 等生图工具的界面稿提示词。  
产品定位：**AI 漫剧 + 科普视频 + 创作工具台**（后续电商小工具）。视觉延续现有 PRINTFILM token，不另起品牌。

相关对照：[PRINTFILM_UI_ROADMAP.md](./PRINTFILM_UI_ROADMAP.md)

---

## 用法

1. 复制 **P0 全局 System**。
2. 追加目标页的 **Page Prompt**（P1–P11）。
3. 追加文末 **Negative / Avoid**。
4. 固定后缀（可并入 System）：

```text
UI mockup, desktop web app, 1440px wide, light theme, PRINTFILM brand, flat clean layout, no 3D clutter, high-fidelity product screenshot, Chinese UI labels
```

- Midjourney：`--ar 16:9 --style raw`（或 `--ar 3:2`）；Negative 放 `--no`。
- GPT Image / Figma AI：三段拼成一条；可加 `exact hex colors, design system consistency`。
- 仅 P1 / P2 / P6 需要手机稿时，在 Page Prompt 末尾加一行：`mobile variant 390px width, same brand, simplified top nav hamburger`。

**拼贴模板：**

```text
[P0 Global System]

[Page Prompt Px]

[Negative / Avoid]

UI mockup, desktop web app, 1440px wide, light theme, PRINTFILM brand, flat clean layout, no 3D clutter, high-fidelity product screenshot, Chinese UI labels
```

---

## 信息架构（IA）

顶栏三栏，**无左侧边栏**：

| 区 | 内容 |
|----|------|
| 左 | Logo + 字标 `PRINTFILM` |
| 中 | 工作台 · 漫剧 · 科普 · 工具 · 资产/历史 · 定价 |
| 右 | 帮助 · 头像 · 主 CTA「开始创作」 |

**工具**二级：文生图 · 图生图 · 图生产品 · 文生视频 · 视频生视频 ·（末尾）电商 Coming soon。

漫剧 / 科普深度工作台允许全屏自有顶栏，但仍浅色 + 同色 token。

---

## P0 — 全局 System Prompt（每次必带）

```text
Design a high-fidelity UI for PRINTFILM, a Chinese creative platform for AI short drama (漫剧), science explainer videos (科普视频), and AI media tools (text-to-image, image-to-image, image-to-product, text-to-video, video-to-video), with future e-commerce micro-tools.

Brand system (strict):
- Primary accent lime: #B6FF00
- Soft lime wash: #EEFCC8
- Ink text: #111318
- Muted gray text: #6B7280
- Page background: #F7F8FA
- Cards: #FFFFFF, corner radius ~14px, soft shadow 0 8px 28px rgba(17,19,24,0.06)
- Hairline borders: rgba(17,19,24,0.1)
- Primary CTA button: solid #B6FF00 fill, #111318 label, no glow
- Secondary: dark ink button or ghost outline
- Typography: Space Grotesk for English brand wordmark "PRINTFILM"; Noto Sans SC for all Chinese UI copy
- Light theme only; bright maker-tool aesthetic; restrained, not decorative

App shell rules:
- Sticky top navigation, three columns: brand left | center nav links | help + avatar + CTA right
- NO left sidebar dashboard chrome
- Nav items in Chinese: 工作台, 漫剧, 科普, 工具, 资产, 定价
- Main CTA label: 开始创作
- Content width comfortable ~1200–1440px; generous whitespace; few stacked cards
- Home / marketing first viewport reads as ONE composition, not an analytics dashboard
- Tool and drama workspaces feel precise and production-oriented, still light gray canvas

UI language: Simplified Chinese labels throughout. Logo mark + PRINTFILM wordmark top-left.
```

---

## Negative / Avoid（每次必带）

```text
Avoid: purple-to-indigo SaaS gradients, neon glow, dark mode cyberpunk, cream paper magazine layouts with serif display, terracotta accents, newspaper broadsheet columns, dense pill clusters, floating badge stickers on hero, multi-stat KPI strips in first viewport, heavy card grids for marketing, glassmorphism overload, 3D clay icons, Inter/Roboto/Arial as hero type, rounded-full candy buttons everywhere, chat-GPT clone sidebar, Material Design default blue, skeuomorphic video players, cluttered widget walls, emoji icon rows, rainbow charts, stock photo people smiling in office.
```

Midjourney 简写：

```text
--no purple gradient, dark mode, neon glow, cream serif magazine, sidebar dashboard, KPI stat strip, glassmorphism, 3D icons, cluttered cards, emoji
```

---

## P1 — App Shell（顶栏骨架）

```text
PRINTFILM web app shell only: sticky white translucent top bar on #F7F8FA empty content area.
Left: small square logo + Space Grotesk wordmark PRINTFILM.
Center nav (Chinese, equal spacing, one active item with lime #B6FF00 underline): 工作台, 漫剧, 科普, 工具, 资产, 定价.
Right: text link 帮助, circular avatar, lime pill button 开始创作.
Clean hairline bottom border under nav. No sidebar. No hero. No cards. Minimal empty state hint in center: soft muted text 「选择一个产品开始」.
Desktop 1440px product UI screenshot, light theme, exact brand colors.
```

---

## P2 — 工作台首页

```text
PRINTFILM workspace home (工作台), first viewport ONE composition.
Background #F7F8FA with subtle soft lime wash, not flat void.
Hero hierarchy: large PRINTFILM brand presence, one Chinese headline about AI 漫剧与科普视频创作, one short supporting sentence, one CTA group (lime 开始创作 + ghost 浏览工具).
Below headline: TWO large equal entry panels (not tiny cards) — left「AI 漫剧」subtitle 剧本·分集·成片; right「科普视频」subtitle 分镜流水线出片.
Under the two entries: a horizontal tool strip of five compact tool chips — 文生图, 图生图, 图生产品, 文生视频, 视频生视频 — plus a muted last chip「电商工具 · 即将上线」.
Keep top SiteNav visible. NO stats, NO schedules, NO promo badges floating on media, NO card wall of templates in the first viewport.
Desktop 1440px, light PRINTFILM system, Chinese UI.
```

手机变体（可选）：

```text
Same page as mobile 390px: brand + headline + stacked 漫剧/科普 entries + horizontal scroll tool chips; hamburger nav; same colors.
```

---

## P3 — 漫剧列表 / Agent 入口

```text
PRINTFILM 漫剧 list page under top nav (漫剧 active with lime underline).
Page header: title「我的漫剧」+ lime button「新建漫剧」+ secondary「自由画布」.
Two creation affordances near top: card or segmented actions「AI 生剧本」and「自由画布」.
Main area: responsive grid of project cards — white 14px radius, soft cover thumbnail, title, episode count, status pill (草稿/生成中/已完成), last edited time. Sparse, 6–9 cards max visible, not overcrowded.
Subtle empty-state friendly if few projects. Light #F7F8FA canvas. Chinese UI. No left sidebar. No purple accents.
```

---

## P4 — 漫剧项目工作台

```text
PRINTFILM drama project workspace, light tool UI, deeper utility density than marketing pages but still #F7F8FA / white panels / lime accent.
Top: project-specific header (may replace marketing SiteNav) with project title, steps or tabs in Chinese: 大纲, 资产, 分集, back link.
Left or top: outline / episode list; center: script or episode cards; right or bottom: asset thumbnails (characters, scenes, props) with small lime generate actions.
Show one selected episode detail with duration and status. Buttons: 生成分集, 打开画布, 绑定音色 — lime primary + ghost secondary.
Precise alignment, hairline dividers, 14px panels, no dark mode, no neon. Desktop wide layout ~1440px Chinese UI screenshot.
```

---

## P5 — 科普创作台（分镜流水线）

```text
PRINTFILM 科普视频 studio storyboard workbench.
Horizontal stepper at top in Chinese: 风格配置 → 分镜 → 成片编辑 (middle step active).
Main: storyboard table or shot list — shot number, thumbnail, narration text, duration, actions 重绘 / 重生视频 / 重配音.
Toolbar: 继续生成, 合成成片, 预览, progress. Lime primary for 合成成片.
Progress bar with lime fill for generation status. White panels on #F7F8FA, 14px radius, SiteNav or studio header.
Feels like a production pipeline, not a social feed. Chinese labels. No sidebar analytics.
```

---

## P6 — 工具 · 文生图

```text
PRINTFILM AI tool page「文生图」inside app shell (工具 active or submenu).
Two-column layout: LEFT control panel (~360px) white card — prompt textarea (提示词), negative prompt, aspect ratio chips 1:1 / 16:9 / 9:16, style preset dropdown, count stepper, large lime button「生成」; RIGHT result gallery masonry or 2×2 grid of generated images with hover download/edit icons.
Top of page: tool title + short description. Credits or queue hint in muted text, not a KPI strip.
Light theme, #B6FF00 CTA, Chinese UI, clean maker tool, no chat sidebar.
```

手机变体（可选）：

```text
文生图 mobile 390px: prompt stacked above results grid; sticky bottom 生成 button lime.
```

---

## P7 — 工具 · 图生图

```text
PRINTFILM tool「图生图」: left panel with large dashed upload zone「上传参考图」, strength slider「相似度」, prompt field, lime「生成」; right side before/after or result grid showing variations of the uploaded subject.
Same PRINTFILM shell and tokens. Chinese labels. White cards 14px, #F7F8FA background. No purple, no dark neon.
```

---

## P8 — 工具 · 图生产品

```text
PRINTFILM tool「图生产品」(product shot generator): upload product photo, toggles for 白底图 / 场景图 / 详情长图, background color chips, lime「生成商品图」; right preview of clean e-commerce product images on white and lifestyle scene.
Professional commerce-adjacent but still PRINTFILM lime system, not Shopify purple. Chinese UI desktop mockup.
```

---

## P9 — 工具 · 文生视频

```text
PRINTFILM tool「文生视频」: left script textarea「视频脚本」, duration selector 5s/10s/15s, aspect 16:9 / 9:16, model or quality select; lime「生成视频」; right video preview player with simple scrubber and shot timeline strip under it.
Light gray studio chrome, lime accents only, Chinese labels, top nav visible. Clean, not YouTube clone clutter.
```

---

## P10 — 工具 · 视频生视频

```text
PRINTFILM tool「视频生视频」: left source video dropzone with filmstrip thumbnail, transform parameters (motion strength, style reference image optional, prompt), lime「开始变换」; right output preview and version history list of short clips.
Same brand shell. Precise tool layout, Chinese UI, #B6FF00 primary, #F7F8FA background.
```

---

## P11 — 电商工具占位

```text
PRINTFILM tools overview grid focused on future e-commerce micro-tools section.
Section title「电商小工具」with muted badge「即将上线」.
Grid of 4–6 disabled/coming-soon tool cards: same white 14px card style but reduced opacity or dashed border — example labels 主图拼接, 详情页排版, 口播字幕条, 价格标签生成 — each with lock or Coming soon caption, no working CTA (ghost disabled).
Above or beside: the five live AI tools still look active with lime accents.
Top nav 工具 active. Chinese UI. Communicate roadmap without looking broken. Light PRINTFILM system.
```

---

## 组件一致性（局部补图）

需要单独出按钮 / 表单 / 空状态时，在 P0 + Negative 后追加其一：

### 按钮组

```text
PRINTFILM button set on white: (1) solid lime #B6FF00 label 开始创作 ink text, (2) solid ink #111318 label 保存 white text, (3) ghost outline hairline label 取消. Corner radius ~10–14px, medium padding, Space Grotesk/Noto Sans SC, no glow, no pill-full unless specified. Flat UI kit sheet.
```

### 输入与控件

```text
PRINTFILM form controls: text input, textarea, select, checkbox, lime-filled slider, segment chips; hairline borders, 10–14px radius, focus ring soft lime #EEFCC8. Chinese placeholder text. Light UI kit on #F7F8FA.
```

### 空状态

```text
PRINTFILM empty state panel: simple line illustration monochrome/lime, Chinese title「还没有项目」, subtitle one line, lime button「新建」. White card 14px on #F7F8FA, no emoji, no 3D.
```

### 加载 / 队列

```text
PRINTFILM generation loading: subtle lime progress bar, muted status「队列中 · 预计 1 分钟」, cancel ghost link. Inside white tool panel. No spinners with purple, no skeleton chaos.
```

---

## 推荐生成顺序

| 顺序 | ID | 目的 |
|------|-----|------|
| 1 | P1 | 锁定壳层与导航 |
| 2 | P2 | 锁定多产品首页构图 |
| 3 | P6 | 锁定工具页双栏范式（可复用到 P7–P10） |
| 4 | P3 → P4 | 漫剧列表与工作台 |
| 5 | P5 | 科普流水线 |
| 6 | P7–P10 | 其余工具 |
| 7 | P11 | 电商占位 |
| 8 | 组件条 | 补齐 UI kit |

同一会话内先出 P1，再以 P1 为参考图做 Image-to-Image / style reference，可显著提高跨页一致性。

---

## 与现网对照（勿在提示词里写死旧路由）

| 现况 | 设计稿方向 |
|------|------------|
| 顶栏：首页 / 模板 / 创作台 / 漫剧 / 历史 / 定价 | 改为：工作台 / 漫剧 / 科普 / 工具 / 资产 / 定价 |
| 工具能力嵌在漫剧画布节点 | 提升为独立「工具」产品区 |
| 石灰绿 token 已存在 | 生图必须沿用，勿换主色 |

实现前端重排时另开任务；本文仅服务视觉探索与设计对齐。
