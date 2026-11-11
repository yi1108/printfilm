import { getActiveLocale, type Locale } from './detect.ts'

/** Static storyboard UI only. User titles, narration and prompts must never pass through this dictionary. */
export const storyboardEnglish: Record<string, string> = {
  '镜号': 'Shot number', '旁白': 'Narration', '画面描述': 'Visual description', '时长秒': 'Duration (seconds)', '状态': 'Status', '镜头标题': 'Shot title',
  '加载失败': 'Failed to load', '生成中…': 'Generating…', '去风格页生成分镜': 'Generate storyboard on the style page', '确认分镜，生成参考图画面': 'Confirm storyboard and generate reference images', '使用图片，逐镜生成视频': 'Generate shot videos from images', '继续生成': 'Continue generation',
  '主题解析': 'Topic analysis', '分镜脚本': 'Storyboard script', '镜头拼接': 'Join shot videos', '成片渲染': 'Render final video',
  '继续生成失败': 'Failed to continue generation', '合成失败': 'Composition failed', '推倒重做': 'Start over',
  '将清空当前分镜与素材，重新拆分镜（生成后仍可先确认再继续）。': 'This will clear the current storyboard and media and create a new storyboard. You can review it before continuing.',
  '确认重做': 'Confirm restart', '再想想': 'Go back', '重做失败': 'Failed to restart', '删除项目': 'Delete project',
  '确定删除该项目？素材与成片将一并清除，此操作不可恢复。': 'Delete this project? All media and the final video will also be deleted. This cannot be undone.',
  '删除': 'Delete', '取消': 'Cancel', '删除失败': 'Failed to delete', '停止失败': 'Failed to stop', '下载失败': 'Download failed', '封面上传失败': 'Cover upload failed',
  '暂无可用镜头画面': 'No shot images available', '设置封面失败': 'Failed to set cover', '请输入有效时长（秒）': 'Enter a valid duration in seconds', '请设置时长，或勾选重配音': 'Set a duration or select voiceover regeneration', '批量调整失败': 'Batch update failed', '发布失败': 'Failed to publish', '生成画面失败': 'Image generation failed', '生成视频失败': 'Video generation failed', '重配音失败': 'Voiceover regeneration failed', '分镜时长不合法': 'Invalid shot duration', '保存失败': 'Failed to save', '保存提示词失败': 'Failed to save prompts', '恢复模板失败': 'Failed to restore template',
  '加载中…': 'Loading…', '开端': 'Opening', '发展': 'Development', '转折': 'Turning point', '高潮': 'Climax', '结局': 'Ending',
  'AI 生成故事板 / 分镜工作台': 'AI storyboard / Shot workspace', '预览成片': 'Preview final video', '拼接成片': 'Compose final video', '批量调整': 'Batch adjust', '用当前镜头重新拼接': 'Recompose using the current shots', '重新拼接': 'Recompose', '打开编辑器': 'Open editor',
  '项目设置': 'Project settings', '更换封面': 'Change cover', '使用第一个有画面的镜头作为封面': 'Use the first shot with an image as the cover', '用首镜封面': 'Use first shot as cover', '草稿导出': 'Export draft', '项目名称': 'Project name', '进度': 'Progress', '时长': 'Duration', '画面比例': 'Aspect ratio', '成片方式': 'Video mode', '静图成片': 'Still-image video', 'AI 视频': 'AI video', '风格': 'Style', '编辑项目设置': 'Edit project settings', '内置提示词': 'Built-in prompts',
  '生图使用模板画风参考图，并参考前镜画面延续角色、服装与色彩；每镜图片再用于生成视频。': 'Images use the template style reference and the previous shot to maintain characters, clothing and colors. Each shot image is then used to generate video.',
  '角色': 'Characters', '额外': 'Additional', '（空，点击编辑）': '(Empty — click to edit)', '内容由 AI 生成，请注意核对准确性': 'AI-generated content. Please verify its accuracy.', 'AI 生成大纲': 'AI-generated outline', '核心主题': 'Core topic', '完整文案': 'Full script', '一句话主题': 'One-line topic', '结构摘要': 'Structure summary', '等待分镜': 'Waiting for storyboard', '发布': 'Publish', '发布到数字资产市场': 'Publish to the digital asset marketplace', '正在拆分镜…': 'Creating storyboard…',
  '暂无分镜。从风格配置页开始生成后，可先确认修改，再手动开始画面生成。': 'No shots yet. Generate a storyboard from the style page, review and edit it, then start image generation manually.',
  '分镜已就绪。点表格「旁白」改口播（会同步脚本并影响整片配音），点「逐段分镜」改画面节奏与 @duration。确认后按阶段预扣：画面+配音 → 镜头视频 → 合成。': 'Your storyboard is ready. Click Narration to edit the spoken script (also updates the script and full voiceover), or Shot segments to edit pacing and @duration. After confirmation, credits are reserved by stage: images + voiceover → shot videos → composition.',
  '场景': 'Scene', '画面': 'Image', '旁白/台词': 'Narration / Dialogue', '逐段分镜': 'Shot segments', '操作': 'Actions', '生成中': 'Generating', '待出图': 'Awaiting image', '点击编辑旁白与标题': 'Click to edit narration and title', '点击编辑逐段分镜脚本': 'Click to edit the shot segment script', '（点击填写逐段分镜）': '(Click to add shot segments)', '编辑': 'Edit', '重绘画面': 'Regenerate image', '生成画面': 'Generate image', '请先生成该镜画面': 'Generate this shot’s image first', '重生视频': 'Regenerate video', '出视频': 'Generate video', '预览视频': 'Preview video', '更多操作': 'More actions', '重配音': 'Regenerate voiceover', '默认': 'Default', '导出分镜脚本': 'Export storyboard script', '生成进度': 'Generation progress', '批量调整分镜': 'Batch adjust shots', '全选': 'Select all', '统一时长（秒，留空则不改）': 'Duration for all selected shots (seconds; leave blank to keep)', '例如 6': 'e.g. 6', '对所选镜头重新配音': 'Regenerate voiceover for selected shots', '应用': 'Apply',
  '全部提示词': 'All prompts', '画面与旁白': 'Image and narration', '分镜列表名称；图文成片会叠到画面顶部': 'Name in the shot list; overlaid at the top of still-image videos', '副标题': 'Subtitle', '作为分镜说明使用': 'Used as a shot description', '可选，会和标题一起显示在成片中': 'Optional; displayed with the title in the final video', '会同步到脚本旁白段，并影响整片配音（改完需重新生成配音/成片）': 'Updates the narration in the script and affects the full voiceover. Regenerate voiceover and the final video after editing.', '画面提示词（首帧）': 'Image prompt (first frame)', '会同步到脚本首段画面，出图与视频都用这一段': 'Updates the first visual segment in the script, used for both images and video', '描述角色、场景和动作；修改后可重新生成这一张图片': 'Describe characters, setting and action. Regenerate this image after editing.', '逐段分镜脚本（画面节奏与 @duration）': 'Shot segment script (visual pacing and @duration)', '暂无 @duration 标签': 'No @duration tags yet', '运镜备注': 'Camera movement notes', '时长（秒，保存后按 @duration 重算）': 'Duration (seconds; recalculated from @duration on save)', '逐段分镜…': 'Shot segments…', '旁白与标题…': 'Narration and title…', '全部字段': 'All fields', '保存': 'Save', '项目内置提示词': 'Project built-in prompts', '默认跟随后台模板。保存为与模板相同的内容会自动清除覆盖；已生成镜头需点重生成才会更新。': 'Uses the configured template by default. Saving identical content clears the override. Regenerate existing shots to apply changes.', '风格提示词': 'Style prompt', '角色提示词': 'Character prompt', '额外要求': 'Additional requirements', '恢复后台模板': 'Restore configured template', '关闭': 'Close', '暂无预览': 'No preview available',
  '参考图画面 ({done}/{total})': 'Reference images ({done}/{total})', '镜头视频与声音 ({done}/{total})': 'Shot video and audio ({done}/{total})', '配音合成 ({done}/{total})': 'Voiceover synthesis ({done}/{total})', '段落 {number}': 'Section {number}', '场景 {number}': 'Scene {number}', '镜头 {number}': 'Shot {number}', '｜旁白：{narration}': ' | Narration: {narration}', '分镜列表（共 {count} 个场景）': 'Storyboard ({count} scenes)', '另有 {count} 段…': '{count} more segments…',
  '总时长: {duration} | 画面: {images}/{total} 个 | 视频: {videos}/{total} 段 | 清晰度: {resolution}': 'Total duration: {duration} | Images: {images}/{total} | Videos: {videos}/{total} | Resolution: {resolution}', '已选 {selected} / {total} 个镜头': '{selected} / {total} shots selected', '编辑镜头 {number} · 旁白与标题': 'Edit shot {number} · Narration and title', '编辑镜头 {number} · 逐段分镜': 'Edit shot {number} · Shot segments', '编辑镜头 {number} · {mode}': 'Edit shot {number} · {mode}', '合计 {total}s / {max}s': 'Total {total}s / {max}s',
  '单个 @duration 需在 {min}–{max} 秒之间': 'Each @duration must be between {min} and {max} seconds', '镜头时长合计不能超过 {max} 秒（当前 {total}s）': 'Total shot duration cannot exceed {max} seconds (currently {total}s)',
  '选题': 'Topic', '确认分镜': 'Confirm storyboard', '参考图画面': 'Reference images', '镜头视频': 'Shot videos', '合成预览': 'Compose and preview',
  '生成进行中，可在右侧查看各阶段进度。': 'Generation is in progress. Track each stage on the right.', '先在风格页点「生成故事板」，本步只拆分镜脚本（预扣文字模型）。': 'Click Generate storyboard on the style page first. This step only creates the shot script (text-model credits are reserved).', '确认分镜后，使用画风参考图逐镜生成图片，并参考前镜画面保持角色与风格一致。': 'After confirming the storyboard, generate each shot using the style reference and previous shot to keep characters and style consistent.', '图片已齐。使用每镜图片生成视频与声音，后镜参考上一镜尾帧延续画面。': 'All images are ready. Generate video and audio for each shot, using the previous shot’s final frame for continuity.', '镜头视频已齐。检查各镜头画面与声音后，即可合成成片。': 'All shot videos are ready. Review their visuals and audio, then compose the final video.',
  '【字幕：后期叠旁白字幕，简体中文逐句同步】\n【BGM：后期混音 · 轻快专业，音量低于人声】\n@duration:4\n过肩工位操作画面…\n@duration:8\n【旁白·自然语速·同步字幕】口播内容…': '【Subtitles: added in post-production, synchronized to narration】\n【BGM: upbeat professional music mixed below speech】\n@duration:4\nOver-the-shoulder view of someone working…\n@duration:8\n【Narration: natural pace, synchronized subtitles】Spoken narration…',
}

/** Translate a static key, interpolating values verbatim rather than translating inserted user data. */
export function storyboardText(text: string, vars: Record<string, string | number> = {}, locale: Locale = getActiveLocale()): string {
  const translated = locale === 'en' ? storyboardEnglish[text] || text : text
  return translated.replace(/\{(\w+)\}/g, (match, key: string) => vars[key] === undefined ? match : String(vars[key]))
}

/** Localize only known duration diagnostics; arbitrary API errors remain untouched. */
export function storyboardError(message: string, locale: Locale = getActiveLocale()): string {
  const range = message.match(/^单个 @duration 需在 (\d+)–(\d+) 秒之间$/)
  if (range) return storyboardText('单个 @duration 需在 {min}–{max} 秒之间', { min: range[1], max: range[2] }, locale)
  const total = message.match(/^镜头时长合计不能超过 (\d+) 秒（当前 ([\d.]+)s）$/)
  if (total) return storyboardText('镜头时长合计不能超过 {max} 秒（当前 {total}s）', { max: total[1], total: total[2] }, locale)
  return storyboardText(message, {}, locale)
}

/** Curated template IDs only: custom template names must retain their original spelling. */
const templateNames: Record<string, string> = {
  opensource_showcase: 'Open-source showcase', opensource_live_work: 'Live-action workplace', live_street_interview: 'Street interview', live_product_desk: 'Live-action desk demo', portrait_story: 'Portrait photo story', anim_3d: '3D animation', live_cinematic: 'Cinematic live action', live_person: 'Live-action storytelling', photo_realism: 'Photorealism', film_cinematic: 'Cinematic film', noir_thriller: 'Noir thriller', vox_papercut: 'Vox-style paper-cut explainer', docu_warm: 'Warm documentary', kids_flat: 'Flat children’s illustration', soft_anime: 'Soft-lit anime', chalk_whiteboard: 'Chalkboard sketch', cyber_neon: 'Cyber neon', epic_fantasy: 'Epic fantasy', magazine_collage: 'Magazine collage', brand_clean: 'Minimal branding', pixel_retro: 'Retro pixel explainer', retro_vhs: 'Retro VHS', ink_guofeng: 'Chinese ink painting',
}

/** Resolve built-in display names without touching template IDs or custom data. */
export function storyboardTemplateName(id: string, name: string | undefined, locale: Locale = getActiveLocale()): string {
  return locale === 'en' ? templateNames[id] || name || id : name || id
}
