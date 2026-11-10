import { marketText as mt } from '../../features/marketplace/translate'
import { useMarketplaceLocale } from '../../features/marketplace/useMarketplaceLocale'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, defaultsFromTemplate } from '../../api'
import type { Project, Shot, Template } from '../../api'
import AppShell from '../../components/layout/AppShell'
import Stepper from '../../components/ui/Stepper'
import ImageTextStoryboard from './ImageTextStoryboard'
import {
  IconChevronLeft,
  IconDownload,
  IconEdit,
  IconImage,
  IconMonitor,
  IconPlay,
  IconRefresh,
  IconSliders,
  IconTrash,
} from '../../components/ui/Icons'
import { scenePromptForDisplay } from '../../promptDisplay'
import { dialog } from '../../lib/dialog'
import { downloadSingleVideo } from '../../lib/clientDownload'
import { withReturn } from '../../features/marketplace/ui'
import { handleBillingError } from '../../lib/billingError'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import {
  effectiveStatus,
  formatMmSs,
  isRunning,
  kepuBillingPhase,
  kepuPhaseHint,
  kepuStepIndex,
  kepuSteps,
  isProjectWideBusy,
  isShotGenerating,
  shotsByNo,
  shotDisplayDone,
  shotDisplayKind,
  shotDisplayLabel,
  statusLabel,
} from '../../lib/status'
import {
  SEGMENT_SCRIPT_PLACEHOLDER,
  SHOT_DURATION_MAX,
  firstVisualFromScript,
  narrationFromScript,
  parseSegmentScript,
  replaceFirstVisualInScript,
  replaceNarrationInScript,
  shotDisplayDurationSec,
  sumDuration,
  validateSegmentScriptDuration,
} from '../../lib/segmentDuration'

function csvEscape(value: string | number | null | undefined) {
  const s = String(value ?? '')
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function downloadStoryboardCsv(project: Project) {
  const header = ['镜号', '旁白', '画面描述', '时长秒', '状态', '镜头标题']
  const rows = (project.shots || [])
    .slice()
    .sort((a, b) => a.shot_no - b.shot_no)
    .map((s) =>
      [
        s.shot_no,
        s.narration,
        scenePromptForDisplay(s.img_prompt || s.video_prompt || ''),
        shotDisplayDurationSec(s),
        shotDisplayLabel(shotDisplayKind(s, { pipelineMode: project.pipeline_mode })),
        s.overlay_title || '',
      ]
        .map(csvEscape)
        .join(','),
    )
  const bom = '\uFEFF'
  const blob = new Blob([bom + [header.join(','), ...rows].join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${project.title || `project_${project.id}`}_storyboard.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

type PreviewState =
  | {
      kind: 'shot'
      shotNo: number
      imageUrl: string | null
      videoUrl: string | null
      audioUrl: string | null
      caption: string
    }
  | { kind: 'final'; url: string; title: string; bust?: string }
  | null

function shotCaption(shot: Shot) {
  if (shot.overlay_title) {
    return `${shot.overlay_title}${
      shot.overlay_subtitle ? ` · ${shot.overlay_subtitle}` : ''
    }${shot.narration ? `｜旁白：${shot.narration}` : ''}`
  }
  return shot.narration
}

function hasActiveUnifiedTasks(project: Project | null): boolean {
  const activeStatuses = ['pending', 'leased', 'running', 'awaiting_poll', 'awaiting_review', 'cancel_requested']
  return Boolean(
    project?.active_tasks?.some(
      (task) => activeStatuses.includes(task.status),
    ),
  )
}

/** 有任务平台数据时以 active_tasks 为准；COMPOSING 无任务视为拼接失败残留，可重试 */
function isProjectBusy(project: Project | null): boolean {
  if (!project) return false
  if (hasActiveUnifiedTasks(project)) return true
  if (Array.isArray(project.active_tasks) && project.active_tasks.length === 0) {
    return false
  }
  return isRunning(project.status)
}

export default function StoryboardPage() {
  useMarketplaceLocale()
  const { id } = useParams()
  const projectId = Number(id)
  const nav = useNavigate()
  const location = useLocation()
  const [project, setProject] = useState<Project | null>(null)
  const [template, setTemplate] = useState<Template | null>(null)
  const [busy, setBusy] = useState(false)
  // busyShotIds 正在提交单镜图/视频的镜号，可并行，finally 只删自己
  const [busyShotIds, setBusyShotIds] = useState<Set<number>>(() => new Set())
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Shot | null>(null)
  const [editFocus, setEditFocus] = useState<string>('')
  /** 表格入口：旁白列 / 逐段分镜列 / 操作栏「编辑」 */
  const [editMode, setEditMode] = useState<'full' | 'narration' | 'segment'>('full')
  const [promptEdit, setPromptEdit] = useState<{
    style_prompt: string
    character_prompt: string
    extra_prompt: string
  } | null>(null)
  const [preview, setPreview] = useState<PreviewState>(null)
  const [menuShotId, setMenuShotId] = useState<number | null>(null)
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchSelected, setBatchSelected] = useState<number[]>([])
  const [batchDuration, setBatchDuration] = useState('')
  const [batchRegenAudio, setBatchRegenAudio] = useState(false)
  const coverInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    if (!projectId) {
      nav('/studio/new')
      return
    }
    api
      .getProject(projectId)
      .then((p) => {
        if (p.creation_session_id) {
          nav(`/studio/sessions/${p.creation_session_id}?project=${p.id}`, { replace: true })
          return
        }
        setProject(p)
        return api.templates().then(async (list) => {
          const selected = list.find((t) => t.id === p.template_id)
          setTemplate(selected || (p.template_id ? await api.getTemplate(p.template_id) : null))
        })
      })
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
  }, [nav, projectId])

  useEffect(() => {
    if (!project) return
    // Only poll while pipeline is actively running — idle checkpoints
    // (IMAGE_READY / VIDEO_READY / SCRIPT_READY) must not spin forever.
    if (!isProjectBusy(project)) return
    const timer = setInterval(() => {
      api
        .getProject(project.id)
        .then(setProject)
        .catch(() => undefined)
    }, 1500)
    return () => clearInterval(timer)
  }, [project?.id, project?.status, project?.active_tasks])

  useEffect(() => {
    if (menuShotId == null) return
    function onDoc() {
      setMenuShotId(null)
    }
    document.addEventListener('click', onDoc)
    return () => document.removeEventListener('click', onDoc)
  }, [menuShotId])

  const running = isProjectBusy(project)
  const step = project ? kepuStepIndex('board', project) : 2
  const totalDuration = useMemo(
    () => (project?.shots || []).reduce((s, x) => s + shotDisplayDurationSec(x), 0),
    [project?.shots],
  )

  // editScriptText 弹窗中当前编辑的逐段脚本
  const editScriptText = editing?.segment_script || editing?.video_prompt || ''
  // editDurationCheck 弹窗脚本时长校验
  const editDurationCheck = useMemo(
    () => validateSegmentScriptDuration(editScriptText),
    [editScriptText],
  )

  const shots = useMemo(() => shotsByNo(project?.shots), [project?.shots])
  /** 项目字段为空时回显模板默认（与后端 _effective_* 一致） */
  const promptDefaults = useMemo(
    () => (template ? defaultsFromTemplate(template) : null),
    [template],
  )
  const displayPrompts = useMemo(() => {
    if (!project) {
      return { style_prompt: '', character_prompt: '', extra_prompt: '' }
    }
    return {
      style_prompt: (project.style_prompt || '').trim() || promptDefaults?.style_prompt || '',
      character_prompt:
        (project.character_prompt || '').trim() || promptDefaults?.character_prompt || '',
      extra_prompt: (project.extra_prompt || '').trim() || promptDefaults?.extra_prompt || '',
    }
  }, [project, promptDefaults])
  const isFullPipeline = project?.pipeline_mode !== 'image_text'
  /**
   * Full pipeline: need AI videos before compose.
   * VIDEO_READY+ means video stage finished (incl. privacy skips without video_url).
   * image_text skips the video stage entirely.
   */
  const phase = project ? kepuBillingPhase(project) : 'script'
  const readyToCompose = phase === 'compose'
  const needsVideos = phase === 'videos'
  const needsScriptConfirm = phase === 'assets'
  const hasFinal = Boolean(project?.final_video_url)
  /** Primary CTA: confirm script → generate → (videos) → compose → preview */
  const primaryAction: 'generate' | 'compose' | 'preview' | 'busy' = running
    ? 'busy'
    : hasFinal
      ? 'preview'
      : readyToCompose
        ? 'compose'
        : 'generate'

  const generateLabel = running
    ? '生成中…'
    : shots.length === 0
      ? '去风格页生成分镜'
      : needsScriptConfirm
        ? '确认分镜，生成参考图画面'
        : needsVideos
          ? '使用图片，逐镜生成视频'
          : '继续生成'

  // 完整模式的默认旁白由视频模型生成；仅实际存在外部配音时展示 TTS 进度。
  const progressItems = useMemo(() => {
    if (!project) return []
    const list = project.shots || []
    const imgs = list.filter((s) => s.image_url).length
    const auds = list.filter((s) => s.audio_url).length
    const vids = list.filter((s) => s.video_url).length
    const full = project.pipeline_mode !== 'image_text'
    const stage = effectiveStatus(project)
    type ProgressItem = { label: string; done: boolean; run?: boolean; pct?: number }
    const items: ProgressItem[] = [
      { label: '主题解析', done: true },
      { label: '分镜脚本', done: list.length > 0 || !['DRAFT', 'SCRIPTING'].includes(project.status) },
      {
        label: `参考图画面 (${imgs}/${list.length || 0})`,
        done: list.length > 0 && imgs === list.length,
      },
    ]
    if (full) {
      items.push({
        label: `镜头视频与声音 (${vids}/${list.length || 0})`,
        done:
          list.length > 0 &&
          (vids === list.length ||
            ['VIDEO_READY', 'COMPOSING', 'AUDITING', 'DONE'].includes(stage)),
        run: stage === 'VIDEOING',
        pct: stage === 'VIDEOING' ? project.progress : undefined,
      })
    }
    if (!full || auds > 0 || stage === 'AUDIOING') {
      items.push({
        label: `配音合成 (${auds}/${list.length || 0})`,
        done: list.length > 0 && auds === list.length,
        run: stage === 'AUDIOING',
        pct: stage === 'AUDIOING' ? project.progress : undefined,
      })
    }
    items.push({
      label: full ? '镜头拼接' : '成片渲染',
      done: Boolean(project.final_video_url) || project.status === 'DONE',
      run: stage === 'COMPOSING',
      pct: stage === 'COMPOSING' ? project.progress : undefined,
    })
    return items
  }, [project])

  function openFinalPreview() {
    if (!project?.final_video_url) return
    setPreview({
      kind: 'final',
      url: api.assetUrl(project.final_video_url, project.updated_at),
      title: project.title,
      bust: project.updated_at,
    })
  }

  async function continueGenerate() {
    if (!project) return
    setBusy(true)
    setError('')
    try {
      setProject(await api.generate(project.id))
    } catch (err) {
      const msg = err instanceof Error ? err.message : '继续生成失败'
      if (msg.includes('合成成片')) {
        try {
          setError('')
          setProject(await api.compose(project.id))
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : '合成失败')
        }
        return
      }
      setError(msg)
      await handleBillingError(err, nav)
    } finally {
      setBusy(false)
    }
  }

  async function restartGenerate() {
    if (!project) return
    const ok = await dialog.confirm({
      title: '推倒重做',
      message: '将清空当前分镜与素材，重新拆分镜（生成后仍可先确认再继续）。',
      confirmText: '确认重做',
      cancelText: '再想想',
      tone: 'danger',
    })
    if (!ok) return
    setBusy(true)
    setError('')
    try {
      setProject(await api.generate(project.id, { restart: true }))
    } catch (err) {
      const msg = err instanceof Error ? err.message : '重做失败'
      setError(msg)
      await handleBillingError(err, nav)
    } finally {
      setBusy(false)
    }
  }

  async function deleteProject() {
    if (!project) return
    const ok = await dialog.confirm({
      title: '删除项目',
      message: '确定删除该项目？素材与成片将一并清除，此操作不可恢复。',
      confirmText: '删除',
      cancelText: '取消',
      tone: 'danger',
    })
    if (!ok) return
    setBusy(true)
    try {
      await api.deleteProject(project.id)
      nav('/history')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setBusy(false)
    }
  }

  async function composeOnly() {
    if (!project) return
    setBusy(true)
    setError('')
    try {
      setProject(await api.compose(project.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '合成失败')
      await handleBillingError(err, nav)
    } finally {
      setBusy(false)
    }
  }

  async function cancelGeneration() {
    if (!project) return
    setBusy(true)
    setError('')
    try {
      setProject(await api.cancelProject(project.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '停止失败')
    } finally {
      setBusy(false)
    }
  }

  async function downloadFinal() {
    if (!project?.final_video_url) return
    setBusy(true)
    setError('')
    try {
      await downloadSingleVideo({ url: api.assetUrl(project.final_video_url, project.updated_at), title: project.title, projectId: project.id })
    } catch (err) {
      setError(err instanceof Error ? err.message : '下载失败')
    } finally {
      setBusy(false)
    }
  }

  async function onCoverFile(file: File | null) {
    if (!project || !file) return
    setBusy(true)
    setError('')
    try {
      setProject(await api.uploadCover(project.id, file))
    } catch (err) {
      setError(err instanceof Error ? err.message : '封面上传失败')
    } finally {
      setBusy(false)
      if (coverInputRef.current) coverInputRef.current.value = ''
    }
  }

  async function useFirstShotCover() {
    if (!project) return
    const first = [...(project.shots || [])]
      .sort((a, b) => a.shot_no - b.shot_no)
      .find((s) => s.image_url)
    if (!first?.image_url) {
      setError('暂无可用镜头画面')
      return
    }
    setBusy(true)
    setError('')
    try {
      setProject(await api.updateProject(project.id, { cover_url: first.image_url }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '设置封面失败')
    } finally {
      setBusy(false)
    }
  }

  function openBatchAdjust() {
    if (!project) return
    setBatchSelected((project.shots || []).map((s) => s.id))
    setBatchDuration('')
    setBatchRegenAudio(false)
    setBatchOpen(true)
  }

  async function applyBatchAdjust() {
    if (!project || batchSelected.length === 0) return
    const durationVal = batchDuration.trim() === '' ? null : Number(batchDuration)
    if (durationVal != null && (!Number.isFinite(durationVal) || durationVal <= 0)) {
      setError('请输入有效时长（秒）')
      return
    }
    if (durationVal == null && !batchRegenAudio) {
      setError('请设置时长，或勾选重配音')
      return
    }
    setBusy(true)
    setError('')
    try {
      for (const shotId of batchSelected) {
        if (durationVal != null) {
          await api.updateShot(project.id, shotId, { duration: durationVal })
        }
        if (batchRegenAudio) {
          await api.regenAudio(project.id, shotId)
        }
      }
      setProject(await api.getProject(project.id))
      setBatchOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '批量调整失败')
      try {
        setProject(await api.getProject(project.id))
      } catch {
        /* ignore */
      }
    } finally {
      setBusy(false)
    }
  }

  async function publish() {
    if (!project) return
    setBusy(true)
    try {
      await api.publish(project.id)
      nav('/history')
    } catch (err) {
      setError(err instanceof Error ? err.message : '发布失败')
    } finally {
      setBusy(false)
    }
  }

  // 标记本镜请求进行中，不覆盖其它镜
  function markShotBusy(shotId: number) {
    setBusyShotIds((ids) => new Set(ids).add(shotId))
  }

  // 只清自己，避免并行请求互相冲掉锁
  function markShotIdle(shotId: number) {
    setBusyShotIds((ids) => {
      const next = new Set(ids)
      next.delete(shotId)
      return next
    })
  }

  async function regenImage(shot: Shot) {
    if (!project) return
    markShotBusy(shot.id)
    try {
      setProject(await api.regenImage(project.id, shot.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成画面失败')
    } finally {
      markShotIdle(shot.id)
    }
  }

  async function regenVideo(shot: Shot) {
    if (!project) return
    markShotBusy(shot.id)
    try {
      setProject(await api.regenVideo(project.id, shot.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成视频失败')
    } finally {
      markShotIdle(shot.id)
    }
  }

  async function regenAudio(shot: Shot) {
    if (!project) return
    // 重配音会重写整片口播，锁整表避免两路抢写
    setBusy(true)
    try {
      setProject(await api.regenAudio(project.id, shot.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '重配音失败')
    } finally {
      setBusy(false)
    }
  }

  function openShotEdit(shot: Shot, focus = '') {
    setEditFocus(focus)
    if (focus === 'narration') setEditMode('narration')
    else if (focus === 'segment_script') setEditMode('segment')
    else setEditMode('full')
    setEditing({ ...shot })
    setMenuShotId(null)
  }

  function closeShotEdit() {
    setEditing(null)
    setEditFocus('')
    setEditMode('full')
  }

  // 改旁白时同步写入脚本旁白段
  function patchEditingNarration(value: string) {
    if (!editing) return
    const script = editing.segment_script || editing.video_prompt || ''
    const next = replaceNarrationInScript(script, value)
    setEditing({
      ...editing,
      narration: value,
      segment_script: next,
      video_prompt: next,
    })
  }

  // 改首帧画面时同步写入脚本第一段 visual
  function patchEditingVisual(value: string) {
    if (!editing) return
    const script = editing.segment_script || editing.video_prompt || ''
    const next = replaceFirstVisualInScript(script, value)
    setEditing({
      ...editing,
      img_prompt: value,
      segment_script: next,
      video_prompt: next,
    })
  }

  // 改脚本时回填旁白与首帧画面，并同步时长为 @duration 合计
  function patchEditingScript(value: string) {
    if (!editing) return
    const tagged = sumDuration(value)
    setEditing({
      ...editing,
      segment_script: value,
      video_prompt: value,
      narration: narrationFromScript(value),
      img_prompt: firstVisualFromScript(value) || editing.img_prompt,
      duration: tagged > 0 ? tagged : editing.duration,
    })
  }

  async function saveShot() {
    if (!project || !editing) return
    // scriptText 当前编辑中的逐段脚本
    const scriptText = editing.segment_script || editing.video_prompt || ''
    // durationCheck 时长校验结果
    const durationCheck = validateSegmentScriptDuration(scriptText)
    if (!durationCheck.valid) {
      setError(durationCheck.message || '分镜时长不合法')
      return
    }
    setBusy(true)
    try {
      await api.updateShot(project.id, editing.id, {
        narration: editing.narration,
        overlay_title: editing.overlay_title,
        overlay_subtitle: editing.overlay_subtitle,
        img_prompt: editing.img_prompt,
        video_prompt: editing.video_prompt,
        segment_script: editing.segment_script,
        duration: durationCheck.total > 0 ? durationCheck.total : Number(editing.duration) || 4,
        camera: editing.camera,
      })
      closeShotEdit()
      setProject(await api.getProject(project.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  // 保存项目提示词；与后台模板相同则清空覆盖
  async function saveProjectPrompts() {
    if (!project || !promptEdit) return
    setBusy(true)
    try {
      const d = promptDefaults
      const styleOut = promptEdit.style_prompt.trim()
      const charOut = promptEdit.character_prompt.trim()
      const extraOut = promptEdit.extra_prompt.trim()
      const updated = await api.updateProject(project.id, {
        style_prompt: d && styleOut === d.style_prompt ? '' : styleOut,
        character_prompt: d && charOut === d.character_prompt ? '' : charOut,
        extra_prompt: d && extraOut === d.extra_prompt ? '' : extraOut,
      })
      setProject(updated)
      setPromptEdit(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存提示词失败')
    } finally {
      setBusy(false)
    }
  }

  // 清空项目覆盖，后续生成跟随后台模板
  async function restoreTemplatePrompts() {
    if (!project) return
    setBusy(true)
    try {
      const updated = await api.updateProject(project.id, {
        style_prompt: '',
        character_prompt: '',
        extra_prompt: '',
      })
      setProject(updated)
      setPromptEdit(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复模板失败')
    } finally {
      setBusy(false)
    }
  }

  if (!project && !error) {
    return (
      <AppShell active="studio">
        <p className="pf-muted">加载中…</p>
      </AppShell>
    )
  }

  if (!project) {
    return (
      <AppShell active="studio">
        <BillingErrorNotice message={error} />
      </AppShell>
    )
  }

  const structure = (project.shots || []).slice(0, 5).map((s, i) => {
    const labels = ['开端', '发展', '转折', '高潮', '结局']
    return { label: labels[i] || `段落 ${i + 1}`, text: s.narration || s.overlay_title || '—' }
  })

  return (
    <AppShell active="studio" wide>
      {!isFullPipeline ? <>
        {error ? <BillingErrorNotice message={error} /> : null}
        {project.error_msg ? <p className="pf-error">{project.error_msg}</p> : null}
        <ImageTextStoryboard
          key={project.id}
          project={project}
          template={template}
          busy={busy}
          running={running}
          busyShotIds={busyShotIds}
          onBack={() => nav('/history')}
          onSettings={() => nav(`/studio/new?project=${project.id}`)}
          onGenerate={() => void continueGenerate()}
          onCompose={() => void composeOnly()}
          onCancel={() => void cancelGeneration()}
          onRestart={() => void restartGenerate()}
          onExport={() => downloadStoryboardCsv(project)}
          onDownload={() => void downloadFinal()}
          onEditor={() => nav(`/studio/${project.id}/editor`)}
          onEditShot={openShotEdit}
          onPreviewShot={(shot) => setPreview({ kind: 'shot', shotNo: shot.shot_no, imageUrl: shot.image_url, videoUrl: shot.video_url, audioUrl: shot.audio_url, caption: shotCaption(shot) })}
          onRegenImage={(shot) => void regenImage(shot)}
          onRegenAudio={(shot) => void regenAudio(shot)}
        />
        <ProjectMediaCostSummary project={project} />
      </> : <>
      <header className="pf-page-head">
        <div className="pf-page-head-row">
          <div>
            <button type="button" className="pf-back" onClick={() => nav(`/studio/${project.id}/style`)}>
              <IconChevronLeft size={18} />
              AI 生成故事板 / 分镜工作台
            </button>
            <h1 className="pf-page-title">{project.title}</h1>
          </div>
          <div className="pf-toolbar">
            {primaryAction === 'preview' ? (
              <button
                type="button"
                className="pf-btn pf-btn-lime pf-btn-sm pf-btn-icon"
                disabled={busy || !hasFinal}
                onClick={openFinalPreview}
              >
                <IconMonitor size={14} />
                预览成片
              </button>
            ) : primaryAction === 'compose' ? (
              <button
                type="button"
                className="pf-btn pf-btn-lime pf-btn-sm pf-btn-icon"
                disabled={busy || running}
                onClick={composeOnly}
              >
                <IconPlay size={14} />
                拼接成片
              </button>
            ) : (
              <button
                type="button"
                className="pf-btn pf-btn-lime pf-btn-sm pf-btn-icon"
                disabled={busy || running}
                onClick={() =>
                  shots.length === 0 ? nav(`/studio/${project.id}/style`) : void continueGenerate()
                }
              >
                <IconPlay size={14} />
                {generateLabel}
              </button>
            )}
            <button
              type="button"
              className="pf-btn-text"
              disabled={busy || running || shots.length === 0}
              onClick={openBatchAdjust}
            >
              <IconSliders size={15} />
              批量调整
            </button>
            <button
              type="button"
              className="pf-btn-text"
              disabled={busy || running}
              onClick={restartGenerate}
            >
              <IconRefresh size={15} />
              推倒重做
            </button>
            {primaryAction !== 'preview' && hasFinal ? (
              <button type="button" className="pf-btn-text" onClick={openFinalPreview}>
                <IconMonitor size={15} />
                预览成片
              </button>
            ) : null}
            {primaryAction === 'preview' && readyToCompose ? (
              <button
                type="button"
                className="pf-btn-text"
                disabled={busy || running}
                onClick={composeOnly}
title="用当前镜头重新拼接"
            >
              重新拼接
            </button>
            ) : null}
            {primaryAction !== 'generate' && !readyToCompose ? (
              <button
                type="button"
                className="pf-btn-text"
                disabled={busy || running}
                onClick={continueGenerate}
              >
                {generateLabel === '生成中…' ? '继续生成' : generateLabel}
              </button>
            ) : null}
            <button
              type="button"
              className="pf-btn pf-btn-outline pf-btn-sm pf-btn-icon"
              onClick={() => nav(`/studio/${project.id}/editor`)}
            >
              <IconEdit size={14} />
              打开编辑器
            </button>
          </div>
        </div>
        <Stepper
          steps={kepuSteps(project.pipeline_mode)}
          current={step}
          doneThrough={Math.max(0, step - 1)}
        />
        <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0.55rem 0 0' }}>
          {kepuPhaseHint(project)}
        </p>
      </header>

      {error ? <BillingErrorNotice message={error} /> : null}
      <ProjectMediaCostSummary project={project} />
      {project.error_msg ? <p className="pf-error">{project.error_msg}</p> : null}

      <div className="pf-board">
        <aside className="pf-create-col">
          <h3>项目设置</h3>
          {(project.cover_url || template?.preview_cover) ? (
            <img
              src={api.assetUrl(project.cover_url || template?.preview_cover)}
              alt=""
              style={{ width: '100%', borderRadius: 12, aspectRatio: '16/10', objectFit: 'cover' }}
            />
          ) : (
            <div
              style={{
                width: '100%',
                aspectRatio: '16/10',
                borderRadius: 12,
                background: '#e8eaee',
                display: 'grid',
                placeItems: 'center',
                color: 'var(--pf-muted)',
              }}
            >
              <IconImage size={28} />
            </div>
          )}
          <input
            ref={coverInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            hidden
            onChange={(e) => onCoverFile(e.target.files?.[0] || null)}
          />
          <div className="pf-side-actions">
            <button
              type="button"
              className="pf-btn pf-btn-ghost pf-btn-sm pf-btn-icon"
              disabled={busy || running}
              onClick={() => coverInputRef.current?.click()}
            >
              <IconImage size={14} />
              更换封面
            </button>
            <button
              type="button"
              className="pf-btn pf-btn-ghost pf-btn-sm pf-btn-icon"
              disabled={busy || running || !shots.some((s) => s.image_url)}
              onClick={useFirstShotCover}
              title="使用第一个有画面的镜头作为封面"
            >
              <IconImage size={14} />
              用首镜封面
            </button>
            <button
              type="button"
              className="pf-btn pf-btn-ghost pf-btn-sm pf-btn-icon"
              disabled={shots.length === 0}
              onClick={() => downloadStoryboardCsv(project)}
            >
              <IconDownload size={14} />
              草稿导出
            </button>
          </div>
          <ul className="pf-meta-list" style={{ marginTop: '0.85rem' }}>
            <li>
              <span>项目名称</span>
              <span>{project.title}</span>
            </li>
            <li>
              <span>状态</span>
              <span>{statusLabel(project)}</span>
            </li>
            <li>
              <span>进度</span>
              <span>{project.progress}%</span>
            </li>
            <li>
              <span>时长</span>
              <span>
                {Math.floor(totalDuration / 60)
                  .toString()
                  .padStart(2, '0')}
                :
                {Math.floor(totalDuration % 60)
                  .toString()
                  .padStart(2, '0')}
              </span>
            </li>
            <li>
              <span>画面比例</span>
              <span>{project.output_ratio || (project.pipeline_mode === 'image_text' ? '9:16' : '16:9')}</span>
            </li>
            <li>
              <span>成片方式</span>
              <span>{project.pipeline_mode === 'image_text' ? '静图成片' : 'AI 视频'}</span>
            </li>
            <li>
              <span>风格</span>
              <span>{template?.name || project.template_id}</span>
            </li>
          </ul>
          <button
            type="button"
            className="pf-btn pf-btn-ghost pf-btn-block pf-btn-sm"
            onClick={() => nav(`/studio/${project.id}/style`)}
            disabled={running}
          >
            编辑项目设置
          </button>
          <div className="pf-prompt-panel">
            <h4>内置提示词</h4>
            <p className="pf-muted" style={{ fontSize: '0.72rem', margin: '0 0 0.45rem' }}>
              生图使用模板画风参考图，并参考前镜画面延续角色、服装与色彩；每镜图片再用于生成视频。
            </p>
            {(
              [
                ['风格', displayPrompts.style_prompt],
                ['角色', displayPrompts.character_prompt],
                ['额外', displayPrompts.extra_prompt],
              ] as const
            ).map(([label, value]) => (
              <button
                key={label}
                type="button"
                className="pf-prompt-chip"
                disabled={busy || running}
                onClick={() =>
                  setPromptEdit({
                    style_prompt: displayPrompts.style_prompt,
                    character_prompt: displayPrompts.character_prompt,
                    extra_prompt: displayPrompts.extra_prompt,
                  })
                }
              >
                <strong>{label}</strong>
                <span>{(value || '').trim() || '（空，点击编辑）'}</span>
              </button>
            ))}
          </div>
          <p className="pf-muted" style={{ fontSize: '0.75rem', marginTop: '0.75rem' }}>
            内容由 AI 生成，请注意核对准确性
          </p>
        </aside>

        <div className="pf-board-main">
          <div className="pf-outline-grid">
            <article className="pf-create-col">
              <h3>AI 生成大纲</h3>
              <p style={{ margin: 0, fontSize: '0.9rem', lineHeight: 1.65 }}>
                {project.source_text}
              </p>
              <div className="pf-tags">
                <span>核心主题</span>
                <span>{project.source_type === 'script' ? '完整文案' : '一句话主题'}</span>
              </div>
            </article>
            <article className="pf-create-col">
              <h3>结构摘要</h3>
              <ul className="pf-meta-list">
                {structure.length ? (
                  structure.map((s) => (
                    <li key={s.label}>
                      <span>{s.label}</span>
                      <span style={{ maxWidth: '60%', textAlign: 'right' }}>{s.text.slice(0, 36)}</span>
                    </li>
                  ))
                ) : (
                  <li>
                    <span>等待分镜</span>
                    <span>—</span>
                  </li>
                )}
              </ul>
            </article>
          </div>

          <section className="pf-shot-card">
            <div className="pf-shot-card-head">
              <h3>分镜列表（共 {project.shots.length} 个场景）</h3>
              <div className="pf-toolbar">
                {project.status === 'DONE' && hasFinal ? (
                  <button type="button" className="pf-btn pf-btn-lime pf-btn-sm" disabled={busy} onClick={publish}>
                    发布
                  </button>
                ) : null}
                {hasFinal ? (
                  <>
                    <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={openFinalPreview}>
                      预览成片
                    </button>
                    <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={() => nav(withReturn(`/marketplace/from-printfilm?project=${project.id}`, `${location.pathname}${location.search}`))}>
                      {mt("发布到数字资产市场")}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="pf-btn pf-btn-ghost pf-btn-sm"
                    disabled={busy || running || !readyToCompose}
                    onClick={composeOnly}
                  >
                    拼接成片
                  </button>
                )}
              </div>
            </div>
            {project.shots.length === 0 ? (
              <p className="pf-muted" style={{ margin: '1.5rem 0', textAlign: 'center' }}>
                {running
                  ? '正在拆分镜…'
                  : '暂无分镜。从风格配置页开始生成后，可先确认修改，再手动开始画面生成。'}
              </p>
            ) : needsScriptConfirm ? (
              <p className="pf-muted" style={{ margin: '0 0 1rem' }}>
                分镜已就绪。点表格「旁白」改口播（会同步脚本并影响整片配音），点「逐段分镜」改画面节奏与 @duration。确认后按阶段预扣：画面+配音 → 镜头视频 → 合成。
              </p>
            ) : null}
            {project.shots.length === 0 ? null : (
              <div className="pf-shot-table-wrap">
                <table className="pf-shot-table">
                  <thead>
                    <tr>
                      <th className="col-no">场景</th>
                      <th className="col-thumb">画面</th>
                      <th className="col-narr">旁白/台词</th>
                      <th className="col-seg">逐段分镜</th>
                      <th className="col-dur">时长</th>
                      <th className="col-status">状态</th>
                      <th className="col-ops">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shots.map((shot) => {
                      /*
                       * localBusy 本镜请求已发出、任务尚未回写
                       * shotGenerating 本镜任务或本地提交中
                       * pipelineLocked 整片流水线/配音占用
                       * displayKind / done / failed 按素材完备度展示
                       */
                      const localBusy = busyShotIds.has(shot.id)
                      const shotGenerating = isShotGenerating(project, shot.id) || localBusy
                      const pipelineLocked = isProjectWideBusy(project)
                      const rowBusy = busy || pipelineLocked || shotGenerating
                      const displayKind = shotDisplayKind(shot, {
                        pipelineMode: project.pipeline_mode,
                        generating: shotGenerating,
                      })
                      const done = shotDisplayDone(displayKind)
                      const failed = displayKind === 'failed'
                      const sceneTitle =
                        shot.overlay_title?.trim() || `场景 ${String(shot.shot_no).padStart(2, '0')}`
                      const narration = (shot.narration || '').trim()
                      const script = shot.segment_script || shot.video_prompt || ''
                      const { cues, beats } = parseSegmentScript(script)
                      const desc = scenePromptForDisplay(shot.img_prompt).trim()
                      return (
                        <tr key={shot.id}>
                          <td className="col-no">{String(shot.shot_no).padStart(2, '0')}</td>
                          <td className="col-thumb">
                            <button
                              type="button"
                              className="pf-shot-thumb-btn"
                              onClick={() =>
                                setPreview({
                                  kind: 'shot',
                                  shotNo: shot.shot_no,
                                  imageUrl: shot.image_url,
                                  videoUrl: shot.video_url,
                                  audioUrl: shot.audio_url,
                                  caption: shotCaption(shot),
                                })
                              }
                            >
                              {shot.image_url ? (
                                <img
                                  className="pf-shot-thumb"
                                  src={api.assetUrl(shot.image_url, shot.version)}
                                  alt=""
                                />
                              ) : (
                                <div className="pf-shot-thumb empty">
                                  {shotGenerating ? '生成中' : '待出图'}
                                </div>
                              )}
                            </button>
                          </td>
                          <td className="col-narr">
                            <button
                              type="button"
                              className="pf-shot-narration pf-shot-editable"
                              disabled={rowBusy}
                              title="点击编辑旁白与标题"
                              onClick={() => openShotEdit(shot, 'narration')}
                            >
                              <span className="title">{sceneTitle}</span>
                              <span className="line">
                                {narration ? `“${narration}”` : '—'}
                              </span>
                            </button>
                          </td>
                          <td className="col-seg">
                            <button
                              type="button"
                              className="pf-shot-desc pf-shot-editable"
                              disabled={rowBusy}
                              title="点击编辑逐段分镜脚本"
                              onClick={() => openShotEdit(shot, 'segment_script')}
                              style={{ textAlign: 'left', width: '100%' }}
                            >
                              {cues.length > 0 ? (
                                <span className="pf-muted" style={{ display: 'block', fontSize: '0.75rem' }}>
                                  {cues[0]?.replace(/^【|】$/g, '').slice(0, 28)}
                                  {cues[1]
                                    ? ` · ${cues[1].replace(/^【BGM：|】$/g, '').slice(0, 16)}`
                                    : ''}
                                </span>
                              ) : null}
                              {beats.length > 0 ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
                                  {beats.slice(0, 4).map((b, i) => (
                                    <span key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                                      {b.duration > 0 ? (
                                        <span
                                          style={{
                                            flex: '0 0 auto',
                                            fontSize: '0.72rem',
                                            background: '#111',
                                            color: '#fff',
                                            borderRadius: 4,
                                            padding: '1px 5px',
                                          }}
                                        >
                                          {b.duration}s
                                        </span>
                                      ) : null}
                                      <span style={{ fontSize: '0.82rem' }}>
                                        {b.text.length > 42 ? `${b.text.slice(0, 42)}…` : b.text}
                                      </span>
                                    </span>
                                  ))}
                                  {beats.length > 4 ? (
                                    <span className="pf-muted" style={{ fontSize: '0.75rem' }}>
                                      另有 {beats.length - 4} 段…
                                    </span>
                                  ) : null}
                                </div>
                              ) : (
                                desc || '（点击填写逐段分镜）'
                              )}
                            </button>
                          </td>
                          <td className="col-dur">{formatMmSs(shotDisplayDurationSec(shot))}</td>
                          <td className="col-status">
                            <span
                              className={[
                                'pf-shot-status',
                                failed ? 'bad' : done ? '' : 'warn',
                              ]
                                .filter(Boolean)
                                .join(' ')}
                            >
                              {done && !failed ? <span className="mark">✓</span> : null}
                              {shotDisplayLabel(displayKind)}
                            </span>
                          </td>
                          <td className="col-ops">
                            <div className="pf-shot-ops">
                              <button
                                type="button"
                                className="op"
                                disabled={rowBusy}
                                onClick={() => openShotEdit(shot)}
                              >
                                编辑
                              </button>
                              <button
                                type="button"
                                className="op"
                                disabled={rowBusy}
                                onClick={() => regenImage(shot)}
                              >
                                {shot.image_url ? '重绘画面' : '生成画面'}
                              </button>
                              {isFullPipeline ? (
                                <button
                                  type="button"
                                  className="op op-video"
                                  disabled={rowBusy || !shot.image_url}
                                  title={!shot.image_url ? '请先生成该镜画面' : undefined}
                                  onClick={() => regenVideo(shot)}
                                >
                                  {shot.video_url ? '重生视频' : '出视频'}
                                </button>
                              ) : null}
                              {shot.video_url ? (
                                <button type="button" className="op" onClick={() => setPreview({ kind: 'shot', shotNo: shot.shot_no, imageUrl: shot.image_url, videoUrl: shot.video_url, audioUrl: shot.audio_url, caption: shotCaption(shot) })}>
                                  预览视频
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="more"
                                aria-label="更多操作"
                                disabled={rowBusy}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setMenuShotId((id) => (id === shot.id ? null : shot.id))
                                }}
                              >
                                ⋮
                              </button>
                              {menuShotId === shot.id ? (
                                <div className="pf-shot-menu" onClick={(e) => e.stopPropagation()}>
                                  <button
                                    type="button"
                                    disabled={rowBusy}
                                    onClick={() => {
                                      setMenuShotId(null)
                                      regenAudio(shot)
                                    }}
                                  >
                                    重配音
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <div className="pf-shot-footer">
              <span className="pf-muted" style={{ fontSize: '0.82rem' }}>
                总时长: {formatMmSs(totalDuration)} | 画面: {project.shots.filter((s) => s.image_url).length}/{project.shots.length} 个 | 视频:{' '}
                {project.shots.filter((s) => s.video_url).length}/{project.shots.length} 段 | 清晰度: {project.video_resolution || '默认'}
              </span>
              <div className="pf-toolbar">
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm pf-btn-icon"
                  disabled={shots.length === 0}
                  onClick={() => downloadStoryboardCsv(project)}
                >
                  <IconDownload size={15} />
                  导出分镜脚本
                </button>
                <button
                  type="button"
                  className="pf-btn-text"
                  disabled={busy || running}
                  onClick={deleteProject}
                >
                  <IconTrash size={15} />
                  删除项目
                </button>
              </div>
            </div>
          </section>
        </div>

        <aside className="pf-create-col pf-board-settings">
          <h3>生成进度</h3>
          <ul className="pf-progress-list">
            {progressItems.map((item) => (
              <li key={item.label}>
                <span>{item.label}</span>
                <span>
                  {item.done ? (
                    <span className="pf-check">✓</span>
                  ) : item.run ? (
                    `${item.pct ?? 0}%`
                  ) : (
                    '…'
                  )}
                </span>
              </li>
            ))}
          </ul>
          <div className="pf-meter" style={{ marginTop: '1rem' }}>
            <i style={{ width: `${Math.min(100, project.progress)}%` }} />
          </div>
          <p className="pf-muted" style={{ fontSize: '0.82rem' }}>
            {statusLabel(project)}
          </p>
        </aside>
      </div>

      </>}

      {batchOpen && project ? (
        <div className="modal-backdrop" onClick={() => !busy && setBatchOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>批量调整分镜</h3>
            <p className="pf-muted" style={{ marginTop: 0 }}>
              已选 {batchSelected.length} / {project.shots.length} 个镜头
            </p>
            <div
              style={{
                maxHeight: 160,
                overflow: 'auto',
                border: '1px solid var(--pf-border, #e5e7eb)',
                borderRadius: 10,
                padding: '0.5rem 0.75rem',
                marginBottom: '0.75rem',
              }}
            >
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                <input
                  type="checkbox"
                  checked={batchSelected.length === project.shots.length && project.shots.length > 0}
                  onChange={(e) =>
                    setBatchSelected(e.target.checked ? project.shots.map((s) => s.id) : [])
                  }
                />
                全选
              </label>
              {project.shots
                .slice()
                .sort((a, b) => a.shot_no - b.shot_no)
                .map((s) => (
                  <label
                    key={s.id}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}
                  >
                    <input
                      type="checkbox"
                      checked={batchSelected.includes(s.id)}
                      onChange={(e) =>
                        setBatchSelected((prev) =>
                          e.target.checked ? [...prev, s.id] : prev.filter((id) => id !== s.id),
                        )
                      }
                    />
                    镜头 {String(s.shot_no).padStart(2, '0')} · {formatMmSs(shotDisplayDurationSec(s))}
                  </label>
                ))}
            </div>
            <label>
              统一时长（秒，留空则不改）
              <input
                type="number"
                min={1}
                step={0.5}
                placeholder="例如 6"
                value={batchDuration}
                onChange={(e) => setBatchDuration(e.target.value)}
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <input
                type="checkbox"
                checked={batchRegenAudio}
                onChange={(e) => setBatchRegenAudio(e.target.checked)}
              />
              对所选镜头重新配音
            </label>
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
              <button
                type="button"
                className="pf-btn pf-btn-lime"
                disabled={busy || batchSelected.length === 0}
                onClick={applyBatchAdjust}
              >
                应用
              </button>
              <button
                type="button"
                className="pf-btn pf-btn-ghost"
                disabled={busy}
                onClick={() => setBatchOpen(false)}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {editing ? (
        <div className="modal-backdrop" onClick={closeShotEdit}>
          <div
            className={[
              'modal',
              'pf-prompt-modal',
              editMode === 'narration' ? 'pf-prompt-modal--narration' : '',
              editMode === 'segment' ? 'pf-prompt-modal--segment' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onClick={(e) => e.stopPropagation()}
          >
            <h3>
              {editMode === 'narration'
                ? `编辑镜头 ${editing.shot_no} · 旁白与标题`
                : editMode === 'segment'
                  ? `编辑镜头 ${editing.shot_no} · 逐段分镜`
                  : `编辑镜头 ${editing.shot_no} · ${isFullPipeline ? '全部提示词' : '画面与旁白'}`}
            </h3>
            <div className="pf-prompt-modal-scroll">
              {editMode === 'narration' || editMode === 'full' ? (
                <>
                  <label>
                    镜头标题
                    <input
                      autoFocus={editFocus === 'title' || editMode === 'narration'}
                      value={editing.overlay_title || ''}
                      onChange={(e) => setEditing({ ...editing, overlay_title: e.target.value })}
                    />
                    <span className="pf-muted pf-prompt-hint">
                      分镜列表名称；图文成片会叠到画面顶部
                    </span>
                  </label>
                  <label>
                    副标题
                    <input
                      value={editing.overlay_subtitle || ''}
                      onChange={(e) => setEditing({ ...editing, overlay_subtitle: e.target.value })}
                    />
                    <span className="pf-muted pf-prompt-hint">
                      {isFullPipeline ? '作为分镜说明使用' : '可选，会和标题一起显示在成片中'}
                    </span>
                  </label>
                  <label>
                    旁白
                    <textarea
                      autoFocus={editFocus === 'narration'}
                      value={editing.narration}
                      onChange={(e) => patchEditingNarration(e.target.value)}
                      rows={editMode === 'narration' ? 6 : 3}
                    />
                    <span className="pf-muted pf-prompt-hint">
                      会同步到脚本旁白段，并影响整片配音（改完需重新生成配音/成片）
                    </span>
                  </label>
                </>
              ) : null}
              {editMode === 'full' ? (
                <label>
                    {isFullPipeline ? '画面提示词（首帧）' : '画面描述'}
                  <textarea
                    autoFocus={editFocus === 'img_prompt'}
                    value={editing.img_prompt}
                    onChange={(e) => patchEditingVisual(e.target.value)}
                    rows={3}
                  />
                  <span className="pf-muted pf-prompt-hint">
                    {isFullPipeline ? '会同步到脚本首段画面，出图与视频都用这一段' : '描述角色、场景和动作；修改后可重新生成这一张图片'}
                  </span>
                </label>
              ) : null}
              {isFullPipeline && (editMode === 'segment' || editMode === 'full') ? (
                <>
                  <label>
                    逐段分镜脚本（画面节奏与 @duration）
                    <textarea
                      className="pf-prompt-segment"
                      autoFocus={editFocus === 'segment_script' || editMode === 'segment'}
                      value={editing.segment_script || editing.video_prompt || ''}
                      onChange={(e) => patchEditingScript(e.target.value)}
                      rows={editMode === 'segment' ? 8 : 5}
                      placeholder={SEGMENT_SCRIPT_PLACEHOLDER}
                    />
                  </label>
                  <div className="pf-chips pf-prompt-duration-chips">
                    {editDurationCheck.durations.length > 0 ? (
                      editDurationCheck.durations.map((sec, i) => (
                        <span key={`${sec}-${i}`} className="pf-chip" style={{ cursor: 'default' }}>
                          {sec}s
                        </span>
                      ))
                    ) : (
                      <span className="pf-muted" style={{ fontSize: '0.8rem' }}>
                        暂无 @duration 标签
                      </span>
                    )}
                    <span
                      className="pf-muted"
                      style={{
                        fontSize: '0.8rem',
                        marginLeft: 'auto',
                        color: editDurationCheck.valid ? undefined : 'var(--pf-danger, #c0392b)',
                      }}
                    >
                      合计 {editDurationCheck.total}s / {SHOT_DURATION_MAX}s
                    </span>
                  </div>
                  {!editDurationCheck.valid && editDurationCheck.message ? (
                    <p className="pf-error pf-prompt-duration-error">{editDurationCheck.message}</p>
                  ) : null}
                  <label>
                    运镜备注
                    <input
                      value={editing.camera || ''}
                      onChange={(e) => setEditing({ ...editing, camera: e.target.value })}
                    />
                  </label>
                  <div className="pf-prompt-modal-row">
                    <label>
                      时长（秒，保存后按 @duration 重算）
                      <input
                        type="number"
                        value={editing.duration}
                        onChange={(e) => setEditing({ ...editing, duration: Number(e.target.value) })}
                      />
                    </label>
                  </div>
                </>
              ) : null}
            </div>
            <div className="pf-prompt-modal-foot">
              {isFullPipeline && editMode !== 'segment' ? (
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  onClick={() => {
                    setEditMode('segment')
                    setEditFocus('segment_script')
                  }}
                >
                  逐段分镜…
                </button>
              ) : null}
              {isFullPipeline && editMode !== 'narration' ? (
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  onClick={() => {
                    setEditMode('narration')
                    setEditFocus('narration')
                  }}
                >
                  旁白与标题…
                </button>
              ) : null}
              {isFullPipeline && editMode !== 'full' ? (
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  onClick={() => {
                    setEditMode('full')
                    setEditFocus('')
                  }}
                >
                  全部字段
                </button>
              ) : null}
              <span className="pf-prompt-modal-foot-spacer" />
              <button
                type="button"
                className="pf-btn pf-btn-lime"
                disabled={busy || !editDurationCheck.valid}
                onClick={saveShot}
              >
                保存
              </button>
              <button type="button" className="pf-btn pf-btn-ghost" onClick={closeShotEdit}>
                取消
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {promptEdit ? (
        <div className="modal-backdrop" onClick={() => setPromptEdit(null)}>
          <div className="modal pf-prompt-modal" onClick={(e) => e.stopPropagation()}>
            <h3>项目内置提示词</h3>
            <p className="pf-muted" style={{ fontSize: '0.8rem', marginTop: 0 }}>
              默认跟随后台模板。保存为与模板相同的内容会自动清除覆盖；已生成镜头需点重生成才会更新。
            </p>
            <label>
              风格提示词
              <textarea
                value={promptEdit.style_prompt}
                onChange={(e) => setPromptEdit({ ...promptEdit, style_prompt: e.target.value })}
                rows={3}
              />
            </label>
            <label>
              角色提示词
              <textarea
                autoFocus
                value={promptEdit.character_prompt}
                onChange={(e) => setPromptEdit({ ...promptEdit, character_prompt: e.target.value })}
                rows={3}
              />
            </label>
            <label>
              额外要求
              <textarea
                value={promptEdit.extra_prompt}
                onChange={(e) => setPromptEdit({ ...promptEdit, extra_prompt: e.target.value })}
                rows={2}
              />
            </label>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="pf-btn pf-btn-lime"
                disabled={busy}
                onClick={saveProjectPrompts}
              >
                保存
              </button>
              <button
                type="button"
                className="pf-btn pf-btn-ghost"
                disabled={busy}
                onClick={() => void restoreTemplatePrompts()}
              >
                恢复后台模板
              </button>
              <button type="button" className="pf-btn pf-btn-ghost" onClick={() => setPromptEdit(null)}>
                取消
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {preview ? (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal preview-modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0 }}>
                {preview.kind === 'final' ? preview.title : `镜头 ${preview.shotNo}`}
              </h3>
              <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={() => setPreview(null)}>
                关闭
              </button>
            </div>
            {preview.kind === 'final' ? (
              <video className="preview-media" src={preview.url} controls autoPlay />
            ) : preview.videoUrl ? (
              <video
                className="preview-media"
                src={api.assetUrl(preview.videoUrl)}
                poster={preview.imageUrl ? api.assetUrl(preview.imageUrl) : undefined}
                controls
                autoPlay
              />
            ) : preview.imageUrl ? (
              <img className="preview-media" src={api.assetUrl(preview.imageUrl)} alt="" />
            ) : (
              <p className="pf-muted">暂无预览</p>
            )}
            {preview.kind === 'shot' && preview.audioUrl ? (
              <audio src={api.assetUrl(preview.audioUrl)} controls style={{ width: '100%' }} />
            ) : null}
            {preview.kind === 'shot' ? <p className="pf-muted">{preview.caption}</p> : null}
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
import { ProjectMediaCostSummary } from '../../components/billing/ProjectMediaCostSummary'
