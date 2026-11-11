# 旧画布迁移到 Printfilm Studio

入口脚本：`backend/scripts/migrate_legacy_canvas.py`，转换/修复逻辑：`backend/app/printfilm_studio/canvas/legacy_migration.py`，测试：`backend/tests/test_legacy_canvas_migration.py`。这些都是保留在源码中的发布文件，不是一次性 SQL。脚本支持任意工作目录，配置使用环境变量及 `backend/.env`，环境变量优先；不执行建表、生成任务或计费操作。

## 操作

```powershell
# 只读检查指定项目（默认不写入）
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --project-id 21

# 备份后迁移指定项目；可重复传 --project-id
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --project-id 21 --apply

# 只读检查所有保存过旧画布节点的项目
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --all

# 开启已验证的历史修复规则，只预览
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --all --repair-legacy

# 批量迁移，保存独立备份和 JSONL 报告
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --all --repair-legacy --apply --backup-dir .tmp/canvas-release/backups --report .tmp/canvas-release/applied.jsonl

# 写入后立即逐份核验备份中的旧数据、资产及目标版本/哈希
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --verify-backups .tmp/canvas-release/backups --report .tmp/canvas-release/verified.jsonl
```

批量写入需显式添加 `--apply`。`--all` 覆盖当前数据库内所有存在 `content.canvas_nodes` 的项目，包含其他用户的项目。每个项目独立事务；未支持的异常项目回滚并报告 `invalid_source`，继续检查其余项目，最终返回非零退出码。非校验类故障（数据库、磁盘等）立即停止，已提交的项目不会撤销。中断后可重复执行，无需清空任何新画布。

`--report` 只创建新文件，拒绝覆盖旧报告，重复执行时换一个报告文件名。报告在项目提交之后写入，包含目标哈希、版本、修复项目和备份路径，不打印提示词或媒体地址。校验成功返回 0，失败返回非零退出码。若校验前已有用户编辑/自动保存，`target_matches` 或 `version_matches` 可能失败；应检查原因，不能因此覆盖用户的新内容。

## 保留和转换

- 从 `drama_projects.content.canvas_nodes/canvas_edges` 转换到 `printfilm_studio_canvas_documents.document`。
- 保留节点 ID、位置、连线、扩展字段及项目内资产关联；角色、场景、道具节点转为图片节点，保留原始类别。
- 图片、视频、音频读取当前资产 URL/封面；文本、提示词、模型、比例、清晰度、时长等字段转换为新画布可用字段。历史 `generating` 状态不会触发任务。
- 不修改旧画布、资产、用户归属、余额、生成历史，不复制媒体文件。
- 不根据整个资产库重建节点，避免恢复用户已经从旧画布删除的节点。
- 非空新画布返回 `skipped_nonempty_target`，带迁移标记的画布返回 `already_migrated`；不会合并或覆盖已有新内容。
- 默认严格模式下，重复节点 ID、无效连线、缺失或跨项目资产引用直接报错。开启 `--repair-legacy` 时只采用下述可追溯修复规则。
- 写入时锁定项目和目标文档，推进文档版本；旧页面提交旧版本会得到版本冲突。

## 历史修复规则（仅修改新副本）

1. **重复 ID**：旧前端按资产 ID 建索引，最后一份布局生效，因此最后一个节点继续使用原 ID，原有连线仍指向它。转换后内容完全相同的节点合并；有任何内容或位置差异的副本保留，分配稳定、无冲突的 `--legacy-` 后缀 ID。修复记录保存来源索引和对应关系。不会把有差异的文本或位置静默丢弃。
2. **已删除资产**：先查全局资产表确认该 ID 确实不存在；仅移除新节点的失效 `assetId`，在 `legacyMissingAssetId` 保存旧引用，保留节点名称、位置、文本和原有媒体快照。若原节点没有媒体地址，保留空媒体节点，不虚构图片或生成新内容。
3. **跨项目资产**：不会解除关联后强行迁移，也不会复制别人的资产；仍报告异常。缺失节点 ID、断开的边、未知节点类型等未确认的异常也保持失败，不做猜测修复。

原始节点数组始终留在旧数据库字段及迁移备份中；每项修复还写入新文档的 `legacyMigration.repairs`、备份和报告。转换器版本为 2，已有 v1 迁移标记继续识别并跳过，不重跑项目 21。

## 备份与回退

写入前将旧画布内容、相关资产快照、目标文档原文及迁移后的版本/哈希写入 `.tmp/legacy-canvas-backups/`。可通过 `--backup-dir` 指定其他目录。备份可能包含私人创作内容和媒体链接，不应提交 Git 或公开分享。

```powershell
backend/.venv/Scripts/python.exe backend/scripts/migrate_legacy_canvas.py --restore "完整备份文件路径.json" --apply
```

回退只恢复新画布文档，并继续递增版本；不会回滚资产、旧画布或删除项目。必须同时匹配迁移后的版本与文档哈希；迁移后发生编辑或自动保存时拒绝回退，以免覆盖后续内容。迁移前不存在新文档时恢复为空文档，不删除记录。

## 上线执行

先发布包含入口脚本、转换模块及新画布模型/codec 的完整后端版本，再单独执行数据迁移；不要把 `--apply` 放进每次 API 启动钩子。`backend/Dockerfile` 已包含 `COPY app ./app` 和 `COPY scripts ./scripts`，会随正常后端镜像打包。

目标库必须已完成 Printfilm Studio 结构迁移，存在 `printfilm_studio_canvas_documents` 表及 `project_id` 唯一约束。结构准备与本脚本的数据迁移分开执行，不通过本脚本临时建表。使用实际部署环境的数据库配置，不把本机 `.env` 拷贝到生产。

Linux 示例（在发布后的 `backend` 或容器 `/app` 目录，Python 环境已安装该后端依赖）：

```bash
# 改成实际挂载、可写且不会随容器替换而丢失的私有备份目录
canvas_backup_dir=/var/backups/printfilm/canvas-release-20261111

# 1. 预览，检查退出码和 ready / skipped / invalid_source
python scripts/migrate_legacy_canvas.py --all --repair-legacy --report "$canvas_backup_dir/preview.jsonl"

# 2. 执行；每项目先落盘备份，再提交新画布
python scripts/migrate_legacy_canvas.py --all --repair-legacy --apply --backup-dir "$canvas_backup_dir/backups" --report "$canvas_backup_dir/applied.jsonl"

# 3. 立即核验：旧画布和资产未改动，新文档版本与哈希一致
python scripts/migrate_legacy_canvas.py --verify-backups "$canvas_backup_dir/backups" --report "$canvas_backup_dir/verified.jsonl"

# 4. 重复预览应只剩 already_migrated / skipped_nonempty_target
python scripts/migrate_legacy_canvas.py --all --repair-legacy --report "$canvas_backup_dir/recheck.jsonl"
```

上面四步按顺序执行并检查每步退出码。先在维护窗口暂停旧画布编辑和生成，以便核验基线稳定；无需删除资产、清库或停数据库。恢复编辑后新文档继续正常使用版本检查。备份应放在私有持久化目录，不能放在可公开访问的 `static` 目录；容器中需事先挂载该路径。部署后保留备份、报告和这一版脚本，便于复查。

## 2026-11-11 第一阶段：项目 21

- 自由画布列表固定每页 8 个；漫剧列表维持原分页设置。
- 项目 21：旧画布 5 个节点、2 条连线、5 个关联图片资产；新画布原为空，版本 3。
- 已迁移到版本 4；重复执行预览返回 `already_migrated`。
- 备份：`.tmp/legacy-canvas-backups/project-21-20261111T035209Z-1d2e8cc4.json`。
- 迁移后的复核时新画布已保存到版本 5；5 个节点 ID、位置、2 条连线、图片 URL 均与迁移来源一致。旧画布及全部资产字段与备份一致。
- 当时全库仅做只读预览：99 个有旧节点的项目中，84 个可迁移、2 个新画布非空、13 个数据异常。预览结果在 `.tmp/legacy-canvas-preview.jsonl`。后续批量迁移结果见下一节。
- 数据异常项目：81、90、92、105、121、137、147、149、227、336、343、345 存在不唯一/无效节点 ID；145 存在缺失或不属于本项目的资产引用。
- 后端迁移、画布 codec 和持久化测试 20 项通过；前端项目目录交互测试通过；TypeScript 和生产构建通过（有现有分包大小警告）。
- 浏览器工具无法可靠检测 Windows 当前 URL，界面验证被工具停止；未完成实际页面视觉验收。

## 2026-11-11 第二阶段：批量迁移与修复

本次只操作当前开发连接的数据库，未执行线上部署或线上迁移。

- 对 99 个项目、1,112 条资产的真实快照在临时 SQLite 副本上演练：96 个项目迁移、校验、重复执行及回退全部通过。副本自动清理，未对真实数据库执行回退。
- 当前环境正式新增迁移 **96 个项目、835 个节点、31 条连线**；其中修复 **13 个项目**。项目 21 原迁移标记被识别并跳过；项目 **8、417** 已有非空新画布，跳过。
- 修复中合并 11 个转换后完全相同的重复节点，给 5 个有差异的副本分配新 ID；项目 145 的 1 个节点移除了已删除资产 2841 的引用。该节点原来没有媒体地址，仅保留名称、位置等内容，未恢复不存在的媒体。
- 正式迁移生成的 **96 份备份全部通过核验**。独立比较完整行哈希确认 **99 条旧项目记录、1,112 条资产记录、项目 8/21/417 的已有新画布完全未变**。
- 实际再次带 `--apply` 执行：97 个 `already_migrated`、2 个 `skipped_nonempty_target`，新增写入 0。
- 后端迁移、修复、codec、持久化测试 **32 项通过**；这次未改前端。

完整本地证据目录：`.tmp/legacy-canvas-rollout-20261111/`，包括 `preview.jsonl`、`rehearsal.json`、`baseline-hashes.json`、`applied.jsonl`、`verified.jsonl`、`preservation-audit.json`、`repeat.jsonl` 和 `backups/`。这些是私有运行产物，保持 Git 忽略；源码脚本与本文档随发布保留。

| 项目 | 原节点数 | 新节点数 | 修复 |
| --- | ---: | ---: | --- |
| 81 | 4 | 3 | 合并 1 个相同副本 |
| 90 | 4 | 3 | 合并 1 个相同副本，保留 1 个有差异副本 |
| 92 | 3 | 2 | 合并 1 个相同副本 |
| 105 | 4 | 3 | 合并 1 个相同副本 |
| 121 | 7 | 5 | 合并 2 个相同副本 |
| 137 | 4 | 2 | 合并 2 个相同副本 |
| 145 | 1 | 1 | 保留空媒体节点，解除已删除资产引用 |
| 147 | 4 | 3 | 合并 1 个相同副本 |
| 149 | 3 | 3 | 保留 1 个不同位置的副本 |
| 227 | 5 | 5 | 保留 1 个有差异副本 |
| 336 | 2 | 1 | 合并 1 个相同副本 |
| 343 | 4 | 3 | 合并 1 个相同副本 |
| 345 | 5 | 5 | 保留 2 个有差异副本 |
