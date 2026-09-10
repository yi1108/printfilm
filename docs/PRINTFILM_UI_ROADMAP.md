# PRINTFILM UI 还原与后续路线图

本文档对应设计图的前端还原结果：已接线能力、与占位清单的关系。

**待开发功能请以 [PLACEHOLDER_BACKLOG.md](./PLACEHOLDER_BACKLOG.md) 为准**（含优先级与代码入口）。本文保留路由对照与视觉约定。

## 路由与设计图对应

| 设计图 | 路由 | 页面组件 |
|--------|------|----------|
| 首页 | `/` | `frontend/src/pages/HomePage.tsx` |
| 新建项目 | `/studio/new` | `frontend/src/pages/studio/CreateProjectPage.tsx` |
| 风格配置 | `/studio/:id/style` | `frontend/src/pages/studio/StyleConfigPage.tsx` |
| 分镜工作台 | `/studio/:id` | `frontend/src/pages/studio/StoryboardPage.tsx` |
| 成片编辑器 | `/studio/:id/editor` | `frontend/src/pages/studio/EditorPage.tsx` |
| 我的项目 / 历史 | `/history` | `frontend/src/pages/HistoryPage.tsx` |
| 模板库 | `/templates` | `frontend/src/pages/TemplatesPage.tsx` |
| 定价 | `/pricing` | `frontend/src/pages/PricingPage.tsx` |

兼容旧入口：`/studio?project=` → `/studio/:id`；`/studio?template=` → `/studio/new?template=`。

共享壳层：`SiteNav` / `AppShell`（`frontend/src/components/layout/`），样式 token 见 `frontend/src/index.css` 与 `frontend/src/styles/printfilm.css`。

## 已实现（接线现有 API）

- 登录 / 注册 / 顶栏用户态
- 帮助中心（侧边抽屉 UI，需前端部署上线）
- 模板列表、分类筛选、从模板进入创作
- 创建项目（主题 / 完整文案）→ 风格配置 → `generate` 启动流水线
- 风格：切换模板预设、风格/角色提示词、音色试听、`pipeline_mode`、画幅
- 分镜台：进度、分镜表、编辑镜头、重绘/重生视频/重配音、继续生成、合成、预览、发布
- 分镜台：批量调时长、CSV 导出、封面上传 / 首镜封面
- 编辑器：场景列表、预览真实媒体、保存旁白、重绘、重配音
- 历史：列表、状态筛选、搜索、类型筛选、继续编辑、预览、删除、批量 zip、**服务端分页**；已发布按 Work 表区分
- 公开作品展示（首页）
- 全局 DialogHost（alert / confirm / prompt）

## 占位与待开发

详见 **[PLACEHOLDER_BACKLOG.md](./PLACEHOLDER_BACKLOG.md)**，按页面与优先级分类。摘要：

| 优先级 | 方向 |
|--------|------|
| P0 | 前端部署（帮助抽屉、续跑状态文案）、队列去重 / 项目互斥 |
| P1 | 链接/文档导入、BGM+字幕、素材上传替换、加镜调序、导出/分享、定价额度 |
| P2 | 通知、社区、风格商店、平台分发、转场以外的编辑器增强 |
| P3 | 福利、点赞播放量、转场、时间线精修、团队空间 |

## 建议迭代优先级（历史）

以下条目已部分落地，保留作对照：

1. ~~P0：编辑器旁白保存 + 分镜重生~~（基本可用，继续打磨失败恢复）
2. ~~P1：封面上传~~（已做）；BGM / 字幕样式仍待做
3. P1：素材库（本地上传替换镜头图）— 仍待做
4. P2：平台导出 / 分享链接；通知中心
5. P2：额度与定价；社区作品流
6. P3：转场、时间线精修、文档/链接导入

## 视觉约定

- 主色石灰绿：`#B6FF00`（`--pf-lime`）
- 背景：`#F7F8FA`（`--pf-bg`）
- 卡片白底、圆角约 14px、轻阴影
- 顶栏居中导航 + 右侧「开始创作」
- 帮助等次要面板：右侧抽屉（`Modal variant=drawer`），避免居中大弹层挡工作台

字体：Space Grotesk（品牌英文）+ Noto Sans SC（正文）。
