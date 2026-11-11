# Printfilm Studio 导演 Skill 落地

日期：2026-11-06。

## 已实现

新增四份自包含的内置 Skill，启动时由现有 `seed_agent_skills()` 同步进 `agent_skills` 表，不需要新增数据库列或手工迁移。

| Skill | 阶段 | 默认选择 | 主要用途 |
| --- | --- | --- | --- |
| `short-drama-assets` | `asset_plan` | 是 | 角色/场景拆解、身份与变体、连续性锁、参考图提示词 |
| `short-drama-storyboard` | `shot_plan` | 是 | 逐镜职责、起止状态、空间连续性、参考节点连线 |
| `short-drama-video-prompts` | `video_prompt` | 是 | 动作、表演、运镜、口型、声音和真实参考职责 |
| `seedance-2-5-video-director` | `video_prompt` | 否，手动替换 | Seedance 2.5 专用文生、首尾帧、多模态、编辑和延长提示词 |

前三项来自 `zenstory-ai/drama-skills`，第四项来自 `liyue-aigc/seedance-2-5-video-director`。各目录保留原 MIT 许可；正文已改成 Printfilm 画布和提示词协议，不依赖原项目的 `references/`、文件工程、脚本或外部生产 API。

当前 `plan_story_assets` 只支持角色和场景节点，因此关键道具的身份、归属和状态写入相关角色/场景描述与提示词，不额外创建道具节点。Seedance 专用 Skill 按本仓库实际能力使用 4–30 秒边界，不引入外部平台的长视频模式。

## 运行方式

- `POST /api/printfilm-studio/agent/sessions/{session_id}/stream` 新增可选字段：
  - `agent_mode`: `director | assistant`，默认 `assistant`，保持旧 API 行为。
  - `skill_task`: `asset_plan | shot_plan | video_prompt`。
  - `skill_ids`: 最多 10 个 ID；`null` 表示全部启用且匹配阶段，`[]` 表示不注入。
- 显式选择后仍按阶段过滤，防止把资产、分镜和多份视频提示词规则同时注入。
- 故事引导 `story_step=assets|shots` 会覆盖普通 `skill_task`，分别使用资产和分镜阶段。
- Agent Run 启动时一次性加载 Skill 并追加到系统提示；断线重放只恢复事件，不重新加载或执行工具。
- 通用助手不注入导演 Skill。

示例：

```json
{
  "prompt": "把这个剧本拆成逐镜规划",
  "agent_mode": "director",
  "skill_task": "shot_plan",
  "skill_ids": [2]
}
```

ID 示例仅说明请求结构，实际应使用 `/api/drama/skills` 返回的 ID。

## 前端

Agent 设置的“导演执导”下新增“Skill 用途”和“导演 Skill”两个选择器。每个阶段只选一个，默认不叠加 Seedance 专用规则。故事引导自动选择对应阶段；Skill 列表加载失败时仍允许无 Skill 继续，不阻止基本创作。

现有漫剧提示词优化入口也会显示四份内置 Skill，可按 `video_prompt` 单独选择通用或 Seedance 专用规则。

## 验证

- Printfilm Studio 后端与 Agent Skill 回归：157 passed。
- 新增导演 Skill 前端测试：4 passed。
- 前端 TypeScript / Vite 构建通过，保留既有混合动态导入与大包提示。
- 前端 oxlint：0 errors，保留仓库既有 44 warnings。
- 前端全量测试含子测试共 244 项：242 passed，2 failed。两个失败均在 `printfilmStudioProposals.test.mjs` 的提案撤销路径，单独复跑相同；本次未修改该路径。
- 差异空白检查通过。

未在功能测试中调用真实上游模型或提交付费生成。

## 本地重启与 seed 结果

- 已按原参数重启本地 8000 后端，前端 5173 未重启。
- 当前配置 `DATABASE_BOOTSTRAP_ENABLED=false`，启动时会跳过自动 seed，因此重启后已单独调用仓库既有 `seed_builtin_skills()` 补跑一次；该操作幂等，保留既有启用开关。
- 数据库已确认四项 Skill 为启用状态，当前 ID 分别为 3、4、5、6；既有 Skill 保留。
- `/api/health` 正常，任务调度与轮询健康；OpenAPI 已包含 `agent_mode`、`skill_task`、`skill_ids`。
- 后续更新内置 Skill 时，如果仍关闭数据库 bootstrap，需要再次执行幂等 seed，不能只重启进程。刷新前端后即可选择新 Skill；真实模型输出质量仍需单独验收。
