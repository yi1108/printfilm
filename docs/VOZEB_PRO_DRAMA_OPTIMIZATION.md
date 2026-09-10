# VOZEB-PRO 漫剧核心逻辑分析与 ai_movie 优化建议

本文记录 `C:\Users\L1822\IdeaProjects\VOZEB-PRO` 中与漫剧相关的核心设计，重点分析三条主链路：

- 分镜 / 镜头拆解
- 用户任务 / 异步 Job 生命周期
- 提交 / 审核 / 发布

目标不是逐字迁移，而是为 `ai_movie` 提供一套可执行的优化蓝图，帮助当前漫剧模块从“可用”走向“更稳、更易扩展、更好运营”。

---

## 1. 结论摘要

`VOZEB-PRO` 在漫剧链路上最值得复用的，不是某个单独接口，而是 3 套边界清晰的基础能力：

1. `DramaProject + DramaShot` 文档模型  
   把“镜头内容”和“镜头生产状态”放在同一个 shot 上，适合前端编辑、回显、重试和恢复。

2. 通用异步任务框架  
   通过任务存储、调度、租约、恢复、轮询、取消和人工接管，把所有 AI 长任务统一治理。

3. 版本化发布流  
   区分草稿版本、当前版本、已发布版本，让“提交审核、驳回修改、再次提交、下架重上架”变成标准流程。

相较之下，`ai_movie` 当前漫剧后端已经具备：

- 项目 / 剧本 / 分集 / 分镜实体
- 分集拆镜
- 分镜视频生成
- 取消与重试
- Celery / in-process 双模式

但核心状态仍然主要挂在 `params` JSON 上，导致幂等、恢复、统计、排障、人工审核等能力偏弱。这正是后续优化重点。

---

## 2. VOZEB-PRO 的核心逻辑

## 2.1 分镜 / 镜头拆解

`VOZEB-PRO` 的漫剧主模型以 `DramaProject` 为总文档，包含角色、场景、道具、线索和分集；每个分集下面再落到 `DramaShot` 这一层。

它的关键点不是“有 shot”，而是 shot 上直接绑定多段状态：

- `storyboardStatus`
- `storyboardEndStatus`
- `generationStatus`
- `audioStatus`

这意味着每个镜头天然就是一个可独立生产、可独立恢复、可独立重试的最小单元。

推荐关注的文件：

- `VOZEB-PRO/web/src/lib/drama-project-contract.ts`
- `VOZEB-PRO/web/src/lib/server/drama-analysis.ts`
- `VOZEB-PRO/web/src/lib/server/drama-project-store.ts`
- `VOZEB-PRO/web/src/app/api/drama/analyze/route.ts`
- `VOZEB-PRO/web/src/app/(user)/drama/[id]/page.tsx`
- `VOZEB-PRO/web/src/app/(user)/drama/[id]/drama-storyboard-shot-card.tsx`
- `VOZEB-PRO/web/src/app/(user)/drama/stores/use-drama-store.ts`

主流程分成两段：

1. `content` 分析  
   从剧本抽出角色、场景、镜头、事件、镜头文本骨架。
2. `visual` 分析  
   给每个 shot 追加视觉提示词、连续性约束、首尾帧说明和视频提示词。

这个拆法很适合 `ai_movie`，因为它把“先把内容结构化”与“再补视觉生产信息”拆开了，能明显降低一次性大提示词失败的风险。

## 2.2 用户任务 / 异步 Job 生命周期

`VOZEB-PRO` 把 AI 异步任务做成了通用框架，而不是散落在业务接口里临时控制。

推荐关注的文件：

- `VOZEB-PRO/web/src/lib/server/generation-task-store.ts`
- `VOZEB-PRO/web/src/lib/server/generation-task-scheduler.ts`
- `VOZEB-PRO/web/src/lib/server/generation-task-recovery-service.ts`
- `VOZEB-PRO/web/src/app/api/maintenance/generation-tasks/run/route.ts`
- `VOZEB-PRO/web/src/app/api/video-generation-tasks/video-generation-route.ts`
- `VOZEB-PRO/web/src/app/api/drama/render/route.ts`

这套框架的典型能力包括：

- 提交前幂等查重
- 并发额度限制
- `lease` 租约抢占
- `nextPollAt` 轮询调度
- 持久化执行阶段
- 取消 / 补偿
- 人工接管与审核
- 恢复服务扫描超时任务

它把“业务状态”和“执行状态”拆成两层：

- 业务状态：镜头是否完成、作品是否可发布
- 执行状态：任务现在是在 `submitting`、`polling`、`persisting` 还是 `needs_review`

这对 `ai_movie` 非常关键，因为当前后端多数进度仍然混在 `script.params`、`episode.params`、`fragment.params` 里。

## 2.3 提交 / 审核 / 发布

`VOZEB-PRO` 的发布流不是简单的“点一次发布”，而是三层版本化模型：

1. `published_works`  
   作品主记录，维护当前版本和已发布版本。
2. `published_work_versions`  
   保存标题、描述、公开 prompt、审核状态等版本化内容。
3. `published_work_assets`  
   绑定版本下的封面和媒体资产。

推荐关注的文件：

- `VOZEB-PRO/web/src/app/api/works/route.ts`
- `VOZEB-PRO/web/src/app/api/works/[id]/route.ts`
- `VOZEB-PRO/web/src/app/api/works/[id]/submit/route.ts`
- `VOZEB-PRO/web/src/lib/server/work-publication-service.ts`
- `VOZEB-PRO/web/src/lib/server/database/work-publication-repository.ts`

这套设计的优点：

- 草稿可反复保存
- 一旦进入审核或已发布，再编辑自动切新版本
- 发布前做强校验
- 审核结果与前台编辑解耦
- 允许下架 / 重上架，而不破坏历史版本

如果 `ai_movie` 未来要把漫剧生成结果进一步产品化、平台化，这套模式会比当前“作品发布 + 简单浏览”更稳。

---

## 3. ai_movie 当前漫剧链路

当前 `ai_movie` 已有一套能工作的漫剧后端流程，主要集中在以下文件：

- `backend/app/api/drama/episodes.py`
- `backend/app/services/drama/access.py`
- `backend/app/services/drama/generation.py`
- `backend/app/services/drama/jobs.py`
- `backend/app/services/ark.py`
- `backend/app/models_drama.py`

当前主流程大致如下：

1. 创建项目与剧本
2. 生成分集内容
3. 从剧本 seed 分集
4. 针对单集做 fragment 规划
5. 保存 / 覆盖 fragments
6. 按集或按镜头提交视频生成
7. 轮询状态
8. 支持取消 / 重试

目前的优点：

- 链路完整，已经覆盖从剧本到片段视频的核心生产
- 兼容 Celery 和本进程 fallback
- 已支持连续性模式，例如沿用上一镜头尾帧
- 已具备一定的任务数量限制和取消能力

目前的短板：

- 状态分散在多个 JSON `params` 字段，缺少统一任务视图
- 幂等键不足，重复提交保护偏弱
- 状态迁移没有集中定义
- 恢复和排障主要靠轮询业务实体
- 用户活跃任务数靠扫 fragment 状态推断
- `save fragments` 为全量替换，稳定 identity 偏弱

---

## 4. 差异对照

## 4.1 分镜模型

`VOZEB-PRO`

- shot 是一等公民
- shot 上直接挂多段生产状态
- 前端 store 可以直接围绕 shot 做排队和重试

`ai_movie`

- `DramaEpisodeFragment` 已接近 shot 粒度
- 但更多是“内容 + 若干 params 状态”
- 状态字段命名与阶段语义还不够统一

建议：

- 把 fragment 明确提升为“生产单元”
- 统一其阶段状态结构，例如：
  - `storyboard.status`
  - `image.status`
  - `video.status`
  - `audio.status`
  - `publish.status`
- 避免继续把所有临时字段直接平铺进 `params`

## 4.2 任务框架

`VOZEB-PRO`

- 有独立任务存储和恢复服务
- 有租约、轮询、人工接管
- 上游异步任务和本地业务状态解耦

`ai_movie`

- 任务状态直接写回 script / episode / fragment
- Celery revoke、Redis purge、内存映射混合控制
- 更偏“业务内嵌式任务”

建议：

- 增加统一任务表，例如 `drama_job_runs`
- 每次 `plan_fragments`、`generate`、`audio`、`publish` 都创建 job
- 业务表保留面向 UI 的汇总状态
- 执行细节、错误、attempt、外部 task id、取消标记统一进 job 表

## 4.3 提交 / 审核 / 发布

`VOZEB-PRO`

- 草稿、提交、审核、发布、下架是完整工作流
- 版本和公开可见状态分离

`ai_movie`

- 当前更偏“生成完成后直接进入作品发布与浏览”
- 如果后续加入公开短剧广场、精选推荐、人工审核，会比较快碰到版本与审核问题

建议：

- 为漫剧作品增加版本化发布模型
- 至少区分：
  - 编辑草稿
  - 待审核版本
  - 已发布版本
- 发布前校验媒体、封面、公开提示词和版权说明

---

## 5. 推荐给 ai_movie 的优化路线

## 5.1 第一阶段：低风险高收益

优先做基础治理，不急着大迁移表结构。

建议项：

1. 统一 fragment 任务状态结构  
   不再混用 `queued / running / generating / done / failed` 的不同层命名，改成统一枚举。

2. 为生成提交加幂等键  
   例如：
   - `client_request_id`
   - `attempt_no`
   - `episode_id + fragment_id + action + fingerprint`

3. 增加结构化任务日志  
   至少记录：
   - 谁提交
   - 何时提交
   - 目标分集 / 分镜
   - 上游 task id
   - 当前阶段
   - 最后错误

4. 把用户任务数统计从扫 `fragment.params` 改成扫任务表或缓存视图

5. 非破坏式更新 fragments  
   先支持按 fragment id 增量更新，保留稳定 identity。

## 5.2 第二阶段：引入统一 Job 表

新增统一任务模型，建议最少包含：

- `id`
- `user_id`
- `project_id`
- `episode_id`
- `fragment_id`
- `job_type`
- `status`
- `execution_phase`
- `client_request_id`
- `attempt_no`
- `provider_task_id`
- `lease_owner`
- `lease_expires_at`
- `next_poll_at`
- `cancel_requested`
- `result_payload`
- `error_code`
- `error_message`

落地方式建议：

1. 新任务先只接入 `fragment video generation`
2. 跑稳后再接 `plan_fragments`
3. 最后接 `audio`、`publish`、`asset generation`

这样能避免一次性重构整个漫剧后端。

## 5.3 第三阶段：拆分 content / visual 两阶段

把当前单集拆镜进一步拆成：

1. `content planning`  
   只产出剧情镜头结构、台词、角色、动作和时长建议。
2. `visual planning`  
   再补足镜头图提示词、视频提示词、连续性约束和参考素材需求。

收益：

- 提示词更短、更稳
- 分镜编辑更自然
- 可单独重跑视觉层，不用重做剧情层

## 5.4 第四阶段：补齐发布审核流

如果后面要做短剧广场、模板化二创、运营精选，建议补：

- 漫剧版本草稿
- 提交审核
- 审核结果
- 已发布版本切换
- 下架 / 重上架

这是产品层能力，但越晚补，迁移成本越高。

---

## 6. 建议的落地顺序

建议按下面顺序实施：

1. 统一 fragment 状态枚举与结构
2. 给生成与拆镜请求补幂等键
3. 建立 `drama_job_runs` 表，先只接视频生成
4. 增加恢复扫描与超时任务接管
5. 把拆镜拆成 `content -> visual`
6. 调整前端，围绕 fragment/shot 单元做局部重试
7. 最后再补版本化发布与审核

这个顺序可以保证：

- 先提升稳定性和可观测性
- 再提升镜头生产体验
- 最后补运营发布能力

---

## 7. 可直接借鉴的设计清单

建议优先借鉴：

- shot 级别的多段状态模型
- `clientRequestId + attemptNo` 幂等模式
- 统一任务存储 + 调度 + 恢复机制
- 任务租约与 `nextPollAt` 调度
- `needs_review` 人工接管状态
- 版本化发布模型

建议谨慎迁移：

- 前端 store 驱动的自动排队编排  
  `ai_movie` 目前后端更重，直接照搬前端编排容易两套调度并存。

- 过度文档化的大 JSON 总文档模型  
  `ai_movie` 现在已有关系表，建议保留关系型实体，只把状态语义向 shot/job 靠拢。

---

## 8. 对 ai_movie 的最终建议

`ai_movie` 不需要整体改造成 `VOZEB-PRO`，但非常值得吸收它的 3 个思想：

1. 用 shot / fragment 作为最小生产单元
2. 用异步任务框架（后台任务治理 + 恢复调度机制）承接所有 AI 异步流程
3. 用版本化发布流承接“创作完成后的内容治理”

如果只做一件事，我建议先做“任务表 + 恢复调度机制”。  
如果做两件事，再加上“content / visual 两阶段拆镜”。  
如果做三件事，再补“版本化发布审核流”。

这样改完后，`ai_movie` 的漫剧链路会从“能生成”升级为“能稳定生产、能恢复、能运营”。
