import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, Clapperboard, Clock3, LoaderCircle, Save, Sparkles } from 'lucide-react'
import { api, type PipelineMode, type Project, type Template, type VoicePreset } from '../../api'
import AppShell from '../../components/layout/AppShell'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import Button from '../../components/ui/Button'
import Stepper from '../../components/ui/Stepper'
import { MediaCostNotice } from '../../components/billing/MediaCostNotice'
import { useMediaModelsCatalog } from '../../hooks/useMediaModelsCatalog'
import { creationTemplateId } from '../../lib/creationTemplates'
import { resolveShortVideoMediaSettings, shortVideoPipelineMode } from '../../lib/shortVideoSettings'
import { isRunning, kepuSteps } from '../../lib/status'
import { dialog } from '../../lib/dialog'
import { useI18n } from '../../i18n'
import './shortVideoCreate.css'

/** 创建短片与检查文案；界面语言不改变项目内容或生成参数。 */
export default function CreateProjectPage() {
  const { m, t } = useI18n()
  const c = m.shortVideoCreate
  const text = (key: string) => t(`shortVideoCreate.${key}`)
  const nav = useNavigate()
  const [params] = useSearchParams()
  const editId = Number(params.get('project')) || null
  const requestedTemplate = creationTemplateId(params.get('template'))
  const requestedPipelineMode = shortVideoPipelineMode(params.get('mode'))
  const returnPath = `/studio/new${params.size ? `?${params}` : ''}`
  const [templates, setTemplates] = useState<Template[]>([])
  const [voices, setVoices] = useState<VoicePreset[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [templateId, setTemplateId] = useState(requestedTemplate)
  const [ratio, setRatio] = useState('9:16')
  const [pipelineMode, setPipelineMode] = useState<PipelineMode>(requestedPipelineMode)
  const [imageModel, setImageModel] = useState('')
  const [videoModel, setVideoModel] = useState('')
  const [imageResolution, setImageResolution] = useState('')
  const [videoResolution, setVideoResolution] = useState('')
  const mediaCatalog = useMediaModelsCatalog()
  const [duration, setDuration] = useState(60)
  const [voice, setVoice] = useState('')
  const [mode, setMode] = useState<'idea' | 'copy'>('idea')
  const [idea, setIdea] = useState('')
  const [copy, setCopy] = useState('')
  const [title, setTitle] = useState('')
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(Boolean(editId))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [voiceError, setVoiceError] = useState(false)
  const working = useRef(false)
  const savedProject = useRef<Project | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  useEffect(() => {
    let disposed = false
    if (!localStorage.getItem('token')) {
      nav(`/auth?next=${encodeURIComponent(returnPath)}`, { replace: true })
      return
    }
    api.templates().then(rows => { if (!disposed) setTemplates(rows) }).catch(cause => { if (!disposed) setError(cause.message || 'templatesFailed') })
    api.voices().then(rows => { if (!disposed) setVoices(rows) }).catch(() => { if (!disposed) setVoiceError(true) })
    return () => { disposed = true }
  }, [nav, editId, returnPath])
  useEffect(() => {
    let disposed = false
    if (!editId) {
      savedProject.current = null
      setProject(null)
      setLoading(false)
      setTemplateId(requestedTemplate)
      setRatio('9:16')
      setPipelineMode(requestedPipelineMode)
      setImageModel('')
      setVideoModel('')
      setImageResolution('')
      setVideoResolution('')
      setDuration(60)
      setVoice('')
      setMode('idea')
      setIdea('')
      setCopy('')
      setTitle('')
      setStep(0)
      return
    }
    // 新建后更新 URL 时，保留当前输入与文案。
    if (savedProject.current?.id === editId) return
    setLoading(true)
    api.getProject(editId).then(value => {
      if (disposed) return
      if (value.creation_session_id) {
        nav(`/studio/sessions/${value.creation_session_id}?project=${value.id}`, { replace: true })
        return
      }
      savedProject.current = value
      setProject(value)
      setTemplateId(creationTemplateId(value.template_id))
      setRatio(value.output_ratio || '9:16')
      setPipelineMode(shortVideoPipelineMode(value.pipeline_mode))
      setImageModel(value.image_model || '')
      setVideoModel(value.video_model || '')
      setImageResolution(value.image_resolution || '')
      setVideoResolution(value.video_resolution || '')
      setDuration(value.target_duration_sec || 60)
      setVoice(value.voice_id || '')
      setTitle(value.title)
      setIdea(value.source_text)
      if (value.source_type === 'script') {
        setCopy(value.source_text)
        setMode('copy')
        setStep(1)
      } else setStep(0)
    }).catch(cause => { if (!disposed) setError(cause.message || 'projectFailed') })
      .finally(() => { if (!disposed) setLoading(false) })
    return () => { disposed = true }
  }, [editId, requestedTemplate, requestedPipelineMode, nav])

  const selectedTemplate = templates.find(item => item.id === templateId)
  const mediaSettings = resolveShortVideoMediaSettings(mediaCatalog, pipelineMode, { imageModel, videoModel, imageResolution, videoResolution, ratio }, project?.ref_image_url ? 3 : 2)
  const running = Boolean(project && (isRunning(project.status) || project.active_tasks?.some(task => ['pending', 'leased', 'running', 'awaiting_poll', 'awaiting_review', 'cancel_requested'].includes(task.status))))
  const disabled = Boolean(busy || loading || running)
  function payload(text: string, name: string) {
    return {
      template_id: templateId, title: name.trim().slice(0, 200) || text.trim().slice(0, 30),
      source_type: 'script' as const, source_text: text.trim(),
      pipeline_mode: pipelineMode, resolution_mode: 'hd' as const,
      output_ratio: mediaSettings.ratio || ratio, target_duration_sec: duration, voice_id: voice,
      image_model: mediaSettings.imageModel, video_model: mediaSettings.videoModel,
      image_resolution: mediaSettings.imageResolution, video_resolution: mediaSettings.videoResolution,
    }
  }
  const draftFields = payload(copy, title)
  const draftChanged = Boolean(project && (
    project.title !== draftFields.title || project.source_text !== draftFields.source_text ||
    project.template_id !== templateId || project.output_ratio !== draftFields.output_ratio ||
    shortVideoPipelineMode(project.pipeline_mode) !== pipelineMode ||
    (project.target_duration_sec || 60) !== duration || (project.voice_id || '') !== voice ||
    (project.image_model || '') !== draftFields.image_model || (project.video_model || '') !== draftFields.video_model ||
    (project.image_resolution || '') !== draftFields.image_resolution || (project.video_resolution || '') !== draftFields.video_resolution
  ))
  const canSaveDraft = !project?.shots.length && !project?.final_video_url
  async function createDraft(text: string, name: string) {
    if (savedProject.current) return savedProject.current
    const value = await api.createProject(payload(text, name))
    savedProject.current = value
    if (mounted.current) {
      setProject(value)
      nav(`/studio/new?project=${value.id}`, { replace: true })
    }
    return value
  }
  async function saveDraft(text: string, name: string) {
    const old = savedProject.current
    if (!old) return createDraft(text, name)
    // Existing generated assets are changed only after the explicit restart confirmation.
    if (old.shots.length || old.final_video_url) return old
    const value = await api.updateProject(old.id, payload(text, name))
    savedProject.current = value
    if (mounted.current) setProject(value)
    return value
  }
  async function saveCopyDraft() {
    if (!copy.trim() || disabled || working.current || !selectedTemplate || !canSaveDraft) return
    working.current = true
    setBusy('savingDraft')
    setError('')
    try {
      await saveDraft(copy, title)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : 'saveFailed')
    } finally {
      working.current = false
      if (mounted.current) setBusy('')
    }
  }
  async function prepareCopy(event: FormEvent) {
    event.preventDefault()
    if (!idea.trim() || disabled || working.current || !selectedTemplate) return
    working.current = true
    setError('')
    setBusy(mode === 'idea' ? 'generatingCopy' : 'savingCopy')
    try {
      const result = mode === 'copy'
        ? { title: title || idea.trim().slice(0, 30), content: idea.trim() }
        : await api.expandContent(idea.trim(), 'script', { target_duration_sec: duration, style: selectedTemplate.name })
      if (!mounted.current) return
      setCopy(result.content)
      setTitle(result.title)
      setStep(1)
      await saveDraft(result.content, result.title)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : 'copyFailed')
    } finally {
      working.current = false
      if (mounted.current) setBusy('')
    }
  }
  async function generateStoryboard() {
    if (!copy.trim() || disabled || working.current || !selectedTemplate) return
    if (!mediaSettings.ready) {
      setError('modelsFailed')
      return
    }
    working.current = true
    try {
      const old = savedProject.current
      if (old?.shots.length) {
        const confirmed = await dialog.confirm({ title: c.restartTitle, message: c.restartMessage, confirmText: c.restartConfirm, tone: 'danger' })
        if (!confirmed || !mounted.current) return
      }
      setBusy('generatingStoryboard')
      setError('')
      let value = await createDraft(copy, title)
      value = await api.updateProject(value.id, payload(copy, title))
      savedProject.current = value
      setProject(value)
      await api.generate(value.id, { restart: Boolean(value.shots.length) })
      if (mounted.current) nav(`/studio/${value.id}`)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : 'storyboardFailed')
    } finally {
      working.current = false
      if (mounted.current) setBusy('')
    }
  }

  return <AppShell active="studio">
    <div className="sv-create-page">
      <header className="sv-create-header">
        <div><Link className="sv-back" to="/history"><ArrowLeft size={16} /> {c.myVideos}</Link><h1>{editId ? c.editTitle : c.createTitle}</h1><p>{c.intro}</p></div>
        <Stepper steps={kepuSteps(pipelineMode).map(item => ({ ...item, label: pipelineMode === 'image_text' ? t(`shortVideoCreate.stillSteps.${item.key}`) : t(`shortVideoCreate.steps.${item.key}`) }))} current={pipelineMode === 'full' && step === 1 ? 2 : step} />
      </header>
      {error && <BillingErrorNotice message={Object.hasOwn(c, error) ? text(error) : error} />}
      {loading ? <div className="sv-loading"><LoaderCircle className="sv-spin" size={20} /> {c.loadingProject}</div> : <>
        {running && <div className="sv-running-note">{c.runningNote}<Link to={`/studio/${project!.id}`}>{c.viewWorkspace} <ArrowRight size={15} /></Link></div>}
        <div className="sv-create-grid">
          <main>
            {step === 0 ? <form onSubmit={prepareCopy}>
              <section className="sv-panel">
                <div className="sv-section-heading"><span>01</span><div><h2>{c.styleTitle}</h2><p>{c.styleHint}</p></div></div>
                <div className="sv-style-grid" role="group" aria-label={c.visualStyle}>
                  {templates.map(item => <button key={item.id} type="button" className={`sv-style-card${item.id === templateId ? ' is-selected' : ''}`} disabled={disabled} aria-pressed={item.id === templateId} onClick={() => setTemplateId(item.id)}>
                    <img src={api.assetUrl(item.preview_cover)} alt="" /><div><strong>{c.styles[item.id as keyof typeof c.styles]?.name || item.name}</strong><p>{c.styles[item.id as keyof typeof c.styles]?.description || item.description}</p></div>
                    {item.id === templateId && <span className="sv-style-check"><Check size={14} /></span>}
                  </button>)}
                </div>
              </section>
              <section className="sv-panel">
                <div className="sv-section-heading"><span>02</span><div><h2>{c.contentTitle}</h2><p>{c.contentHint}</p></div></div>
                <div className="sv-input-tabs"><button type="button" className={mode === 'idea' ? 'is-active' : ''} onClick={() => setMode('idea')} disabled={disabled}>{c.ideaTab}</button><button type="button" className={mode === 'copy' ? 'is-active' : ''} onClick={() => setMode('copy')} disabled={disabled}>{c.copyTab}</button></div>
                <label className="sv-field"><span>{mode === 'idea' ? c.ideaLabel : c.copyLabel}</span><textarea aria-label={mode === 'idea' ? c.ideaLabel : c.copyLabel} value={idea} onChange={event => setIdea(event.target.value)} rows={6} maxLength={20000} disabled={disabled} placeholder={mode === 'idea' ? c.ideaPlaceholder : c.copyPlaceholder} required /></label>
                {mode === 'idea' && <div className="sv-examples">{c.examples.map(example => <button type="button" key={example} onClick={() => setIdea(example)} disabled={disabled}>{example}</button>)}</div>}
                <div className="sv-actions"><span>{c.copyHint}</span><div className="sv-action-buttons">{copy.trim() && <Button variant="outline" disabled={disabled} onClick={() => setStep(1)}>{c.editCopy}</Button>}<Button type="submit" variant="lime" disabled={disabled || !idea.trim() || !selectedTemplate}>{busy ? <LoaderCircle size={16} className="sv-spin" /> : <Sparkles size={16} />}{(busy && text(busy)) || (mode === 'idea' ? c.generateCopy : c.reviewNext)}<ArrowRight size={16} /></Button></div></div>
              </section>
            </form> : <section className="sv-panel">
              <div className="sv-section-heading"><span>02</span><div><h2>{c.reviewTitle}</h2><p>{c.reviewHint}</p></div></div>
              <label className="sv-field"><span>{c.videoName}</span><input value={title} onChange={event => setTitle(event.target.value)} maxLength={200} disabled={disabled} /></label>
              <label className="sv-field"><span>{c.narrationScript} <small>{t('shortVideoCreate.characterCount', { count: copy.length })}</small></span><textarea aria-label={c.narrationScript} value={copy} onChange={event => setCopy(event.target.value)} rows={13} maxLength={20000} disabled={disabled} /></label>
              <div className="sv-actions"><Button variant="outline" disabled={disabled} onClick={() => setStep(0)}><ArrowLeft size={15} /> {c.back}</Button><div className="sv-action-buttons">{canSaveDraft && <Button variant="outline" disabled={disabled || !copy.trim() || !selectedTemplate || Boolean(project && !draftChanged)} onClick={() => { void saveCopyDraft() }}><Save size={15} />{c.saveDraft}</Button>}<Button variant="lime" disabled={disabled || !copy.trim() || !selectedTemplate} onClick={() => { void generateStoryboard() }}>{busy ? <LoaderCircle size={16} className="sv-spin" /> : <Clapperboard size={16} />}{(busy && text(busy)) || c.generateStoryboard}<ArrowRight size={16} /></Button></div></div>
              {project && <p className="sv-saved-note">{draftChanged ? canSaveDraft ? c.unsavedDraft : c.unsavedRestart : canSaveDraft ? c.draftSaved : c.scriptLoaded}<Link to={`/studio/${project.id}`}>{c.openWorkspace}</Link></p>}
            </section>}
          </main>
          <aside className="sv-panel sv-settings">
            <h2>{c.settingsTitle}</h2><p>{c.settingsHint}</p>
            <div className="sv-field"><span>{c.outputMode}</span><div className="sv-output-modes" role="group" aria-label={c.outputMode}>{([{ id: 'full', label: c.aiVideo, desc: c.aiVideoDesc }, { id: 'image_text', label: c.stillVideo, desc: c.stillVideoDesc }] as const).map(item => <button key={item.id} type="button" className={pipelineMode === item.id ? 'is-selected' : ''} aria-pressed={pipelineMode === item.id} disabled={disabled} onClick={() => setPipelineMode(item.id)}><strong>{item.label}</strong><span>{item.desc}</span>{pipelineMode === item.id && <Check size={14} />}</button>)}</div></div>
            <label className="sv-field"><span>{c.aspectRatio}</span><select value={mediaSettings.ratio} onChange={event => setRatio(event.target.value)} disabled={disabled || !mediaSettings.ratios.length}>{!mediaSettings.ratios.length && <option value="">{c.noCommonRatio}</option>}{mediaSettings.ratios.map(value => <option key={value} value={value}>{value}{value === '9:16' ? ` ${c.portrait}` : value === '16:9' ? ` ${c.landscape}` : value === '1:1' ? ` ${c.square}` : ''}</option>)}</select></label>
            <label className="sv-field"><span>{c.duration}</span><select value={duration} onChange={event => setDuration(Number(event.target.value))} disabled={disabled}>{[...new Set([30, 60, 90, 120, 180, duration])].sort((a, b) => a - b).map(value => <option key={value} value={value}>{t('shortVideoCreate.durationOption', { seconds: value })}</option>)}</select></label>
            {pipelineMode === 'image_text' ? <>
              <label className="sv-field"><span>{c.voice}</span><select value={voice} onChange={event => setVoice(event.target.value)} disabled={disabled}><option value="">{c.defaultVoice}</option>{voice && !voices.some(item => (item.speaker || item.id) === voice) && <option value={voice}>{c.existingVoice}</option>}{voices.map(item => <option key={item.id} value={item.speaker || item.id}>{item.label}</option>)}</select></label>
              {voiceError && <p className="sv-saved-note">{c.voiceError}</p>}
            </> : <p className="sv-saved-note">{c.nativeAudio}</p>}
            <details className="sv-model-settings" open={pipelineMode === 'full'}><summary>{c.modelsTitle}</summary>
              <label className="sv-field"><span>{c.imageModel}</span><select value={mediaSettings.imageModel} disabled={disabled || !mediaSettings.imageOptions.length} onChange={event => setImageModel(event.target.value)}>{mediaSettings.imageSelectionUnavailable && <option value={mediaSettings.imageModel} disabled>{t('shortVideoCreate.unavailable', { model: mediaSettings.imageModel })}</option>}{!mediaSettings.imageOptions.length && !mediaSettings.imageSelectionUnavailable && <option value="">{mediaCatalog ? c.noImageModels : c.loadingModels}</option>}{mediaSettings.imageOptions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
              <label className="sv-field"><span>{c.imageResolution}</span><select value={mediaSettings.imageResolution} disabled={disabled || !mediaSettings.imageResolutions.length} onChange={event => setImageResolution(event.target.value)}>{!mediaSettings.imageResolutions.length && <option value={mediaSettings.imageResolution}>{mediaSettings.imageResolution || c.selectModel}</option>}{mediaSettings.imageResolutions.map(value => <option key={value} value={value}>{value}</option>)}</select><MediaCostNotice modelId={mediaSettings.imageModel} resolution={mediaSettings.imageResolution} /></label>
              {pipelineMode === 'full' && <><label className="sv-field"><span>{c.videoModel}</span><select value={mediaSettings.videoModel} disabled={disabled || !mediaSettings.videoOptions.length} onChange={event => setVideoModel(event.target.value)}>{mediaSettings.videoSelectionUnavailable && <option value={mediaSettings.videoModel} disabled>{t('shortVideoCreate.unavailable', { model: mediaSettings.videoModel })}</option>}{!mediaSettings.videoOptions.length && !mediaSettings.videoSelectionUnavailable && <option value="">{mediaCatalog ? c.noVideoModels : c.loadingModels}</option>}{mediaSettings.videoOptions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
                <label className="sv-field"><span>{c.videoResolution}</span><select value={mediaSettings.videoResolution} disabled={disabled || !mediaSettings.videoResolutions.length} onChange={event => setVideoResolution(event.target.value)}>{!mediaSettings.videoResolutions.length && <option value={mediaSettings.videoResolution}>{mediaSettings.videoResolution || c.selectModel}</option>}{mediaSettings.videoResolutions.map(value => <option key={value} value={value}>{value}</option>)}</select><MediaCostNotice modelId={mediaSettings.videoModel} resolution={mediaSettings.videoResolution} seconds={1} /></label></>}
              {mediaCatalog && !mediaSettings.ready && <p className="sv-model-error" role="status">{t('shortVideoCreate.modelHint', { count: project?.ref_image_url ? 3 : 2, videoRequirement: pipelineMode === 'full' ? c.videoRequirement : '' })}</p>}
            </details>
            <div className="sv-setting-summary"><Clapperboard size={17} /><div><strong>{(selectedTemplate && c.styles[selectedTemplate.id as keyof typeof c.styles]?.name) || selectedTemplate?.name || c.styles.anim_3d.name}</strong><span>{pipelineMode === 'full' ? c.imageToVideo : c.imageMotion} · {c.narrationSummary}</span><span>{c.continuityHint}</span></div></div>
            <div className="sv-workflow-hint"><Clock3 size={17} /><p>{pipelineMode === 'full' ? c.fullWorkflow : c.stillWorkflow}</p></div>
          </aside>
        </div>
      </>}
    </div>
  </AppShell>
}
