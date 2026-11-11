import { studioSecondaryText as mt } from '../../i18n/studioSecondaryText'
import { useMarketplaceLocale } from '../../features/marketplace/useMarketplaceLocale'
import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, defaultsFromTemplate, resolveVoiceId } from '../../api'
import type { MediaModelOption, PipelineMode, Project, Template, VoicePreset } from '../../api'
import { resolveCatalogModelSelection, useMediaModelsCatalog } from '../../hooks/useMediaModelsCatalog'
import { MediaCostNotice } from '../../components/billing/MediaCostNotice'
import AppShell from '../../components/layout/AppShell'
import Stepper from '../../components/ui/Stepper'
import ComingSoon from '../../components/ui/ComingSoon'
import { IconChevronLeft, IconPlay } from '../../components/ui/Icons'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import { handleBillingError } from '../../lib/billingError'
import { kepuStepIndex, kepuSteps } from '../../lib/status'

const OUTPUT_MODES: { id: PipelineMode; label: string; desc: string; image: string }[] = [
  { id: 'full', label: 'AI 视频', desc: '图→视频→配音→合成', image: '/mode-presets/full.jpg' },
  {
    id: 'image_text',
    label: '静图成片',
    desc: '静图+叠字+配音，不生成 AI 视频',
    image: '/mode-presets/image_text.jpg',
  },
]

const RATIOS: { id: string; label: string; w: number; h: number }[] = [
  { id: '16:9', label: '16:9', w: 36, h: 20 },
  { id: '9:16', label: '9:16', w: 18, h: 32 },
  { id: '1:1', label: '1:1', w: 24, h: 24 },
  { id: '4:3', label: '4:3', w: 28, h: 21 },
  { id: '21:9', label: '21:9', w: 40, h: 17 },
]

/** 画幅是否竖向（高 > 宽），用于预览卡与实时预览比例 */
/** 音色卡片与 API 试听共用的 speaker 键 */
function voiceKey(v: VoicePreset): string {
  return v.speaker || v.id
}

function isPortraitRatio(ratio: string | undefined | null): boolean {
  const raw = String(ratio || '').trim()
  const m = raw.match(/^(\d+(?:\.\d+)?)\s*[:/x]\s*(\d+(?:\.\d+)?)$/i)
  if (!m) return false
  return Number(m[2]) > Number(m[1])
}

export default function StyleConfigPage() {
  useMarketplaceLocale()
  const { id } = useParams()
  const projectId = Number(id)
  const nav = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [voices, setVoices] = useState<VoicePreset[]>([])
  const [stylePrompt, setStylePrompt] = useState('')
  const [extraPrompt, setExtraPrompt] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [pipelineMode, setPipelineMode] = useState<PipelineMode>('full')
  const [ratio, setRatio] = useState('16:9')
  const [imageModel, setImageModel] = useState('')
  const [videoModel, setVideoModel] = useState('')
  const mediaCatalog = useMediaModelsCatalog()
  const [imageResolution, setImageResolution] = useState('2K')
  const [videoResolution, setVideoResolution] = useState('480p')
  const [busy, setBusy] = useState(false)
  const [previewBusy, setPreviewBusy] = useState<string | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    if (!mediaCatalog) return
    setImageModel(previous => resolveCatalogModelSelection(mediaCatalog, 'image', previous))
    setVideoModel(previous => resolveCatalogModelSelection(mediaCatalog, 'video', previous))
  }, [mediaCatalog, imageModel, videoModel])

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    if (!projectId) {
      nav('/studio/new')
    }
    api.voices().then(setVoices)
    Promise.all([api.templates(), api.getProject(projectId)])
      .then(async ([list, p]) => {
        if (p.pipeline_mode === 'image_text') {
          nav(`/studio/new?project=${p.id}`, { replace: true })
          return
        }
        // 下架的风格不再展示给新用户，历史项目仍可加载其原模板。
        if (p.template_id && !list.some((item) => item.id === p.template_id)) {
          const legacy = await api.getTemplate(p.template_id)
          list = [...list, legacy]
        }
        setTemplates(list)
        setProject(p)
        setStylePrompt(p.style_prompt || '')
        setExtraPrompt(p.extra_prompt || '')
        setVoiceId(p.voice_id || '')
        setPipelineMode(p.pipeline_mode || 'full')
        setRatio(p.output_ratio || '16:9')
        if (p.image_model) setImageModel(p.image_model)
        if (p.video_model) setVideoModel(p.video_model)
        if (p.image_resolution) setImageResolution(p.image_resolution)
        if (p.video_resolution) setVideoResolution(p.video_resolution)
      })
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
  }, [nav, projectId])

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
      audioRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!voices.length) return
    setVoiceId((prev) => {
      const next = resolveVoiceId(prev, voices)
      return next === prev ? prev : next
    })
  }, [voices])

  const currentTpl = useMemo(
    () => templates.find((t) => t.id === project?.template_id),
    [templates, project?.template_id],
  )

  const selectedVoice = voices.find((v) => voiceKey(v) === voiceId || v.id === voiceId)

  useEffect(() => {
    if (!project || !currentTpl) return
    if (!stylePrompt) {
      const d = defaultsFromTemplate(currentTpl)
      setStylePrompt((v) => v || d.style_prompt)
      setExtraPrompt((v) => v || d.extra_prompt)
      setVoiceId((v) => v || d.voice_id)
    }
  }, [project, currentTpl])

  useEffect(() => {
    if (!project || project.output_ratio || !currentTpl?.default_ratio) return
    setRatio(currentTpl.default_ratio)
  }, [project?.id, project?.output_ratio, currentTpl?.default_ratio])

  function pickRatio(r: (typeof RATIOS)[0]) {
    setRatio(r.id)
  }

  function stopPreview() {
    audioRef.current?.pause()
    audioRef.current = null
    setPlayingId(null)
  }

  function selectVoice(v: VoicePreset) {
    const vid = voiceKey(v)
    if (vid !== voiceId) stopPreview()
    setVoiceId(vid)
  }

  async function previewVoice(v: VoicePreset, e: MouseEvent) {
    e.stopPropagation()
    const vid = voiceKey(v)
    selectVoice(v)
    setError('')

    if (playingId === vid && audioRef.current && !audioRef.current.paused) {
      stopPreview()
      return
    }

    stopPreview()
    setPreviewBusy(vid)
    try {
      const res = await api.previewVoice(vid)
      const url = api.assetUrl(res.url)
      const audio = new Audio(url)
      audioRef.current = audio
      audio.onended = () => setPlayingId(null)
      audio.onerror = () => {
        setPlayingId(null)
        setError('试听播放失败')
      }
      setPlayingId(vid)
      await audio.play()
    } catch (err) {
      setError(err instanceof Error ? err.message : '试听失败')
      setPlayingId(null)
    } finally {
      setPreviewBusy(null)
    }
  }

  async function generate() {
    if (!project) return
    const image = mediaCatalog?.image_models.find(item => item.id === imageModel)
    const video = mediaCatalog?.video_models.find(item => item.id === videoModel)
    if (!image || image.available === false || !(image.available_resolutions ?? image.allowed_resolutions ?? []).includes(imageResolution) || !image.allowed_aspect_ratios?.includes(ratio) ||
        (pipelineMode === 'full' && (!video || video.available === false || !(video.available_resolutions ?? video.allowed_resolutions ?? []).includes(videoResolution) || !video.allowed_aspect_ratios?.includes(ratio)))) {
      setError('所选模型不支持当前参数或尚未配置价格，请检查模型、分辨率和画幅。')
      return
    }
    stopPreview()
    setBusy(true)
    setError('')
    try {
      const d = currentTpl ? defaultsFromTemplate(currentTpl) : null
      /*
       * styleOut 风格提示词；与模板相同则留空，生成时读后台
       * extraOut 额外提示词
       */
      const styleOut = stylePrompt.trim()
      const extraOut = extraPrompt.trim()
      const sameStyle = Boolean(d) && styleOut === d!.style_prompt
      const sameExtra = Boolean(d) && extraOut === d!.extra_prompt
      await api.updateProject(project.id, {
        style_prompt: sameStyle ? '' : styleOut,
        character_prompt: '',
        extra_prompt: sameExtra ? '' : extraOut,
        voice_id: voiceId,
        pipeline_mode: pipelineMode,
        output_ratio: ratio,
        image_model: imageModel,
        video_model: videoModel,
        image_resolution: imageResolution,
        video_resolution: videoResolution,
      })
      const started = await api.generate(project.id)
      nav(`/studio/${started.id}`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '生成失败'
      if (msg.includes('合成成片')) {
        try {
          const composed = await api.compose(project.id)
          nav(`/studio/${composed.id}`)
          return
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : '合成失败')
          return
        }
      }
      setError(msg)
      await handleBillingError(err, nav)
    } finally {
      setBusy(false)
    }
  }

  // project 初始加载失败时不得穿透主页面（下方存在 project.xxx 非空访问，会白屏崩溃）
  if (!project) {
    return (
      <AppShell active="studio">
        {error ? <BillingErrorNotice message={mt(error)} /> : <p className="pf-muted">{mt("加载中…")}</p>}
      </AppShell>
    )
  }

  return (
    <AppShell active="studio" wide>
      <header className="pf-page-head">
        <div className="pf-page-head-row">
          <div>
            <button type="button" className="pf-back" onClick={() => nav('/studio/new')}>
              <IconChevronLeft size={18} />{mt("返回创作台")}</button>
            <h1 className="pf-page-title">{project?.title || mt("风格配置")}</h1>
          </div>
          <Stepper
            steps={kepuSteps(pipelineMode).map(item => ({ ...item, label: mt(item.label) }))}
            current={kepuStepIndex('style', { status: 'DRAFT', pipeline_mode: pipelineMode })}
            doneThrough={0}
          />
        </div>
      </header>

      <div className="pf-style-layout">
        <aside className="pf-create-col">
          <h3>{mt("项目信息")}</h3>
          {currentTpl ? (
            <div>
              <div
                className={[
                  'pf-style-side-thumb',
                  isPortraitRatio(currentTpl.default_ratio) ? 'portrait' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <img src={api.assetUrl(currentTpl.preview_cover)} alt="" />
              </div>
              <p style={{ margin: '0.5rem 0 0', fontWeight: 600 }}>{currentTpl.name}</p>
              <div className="pf-tags">
                {currentTpl.category.map((c) => (
                  <span key={c}>{c}</span>
                ))}
              </div>
            </div>
          ) : null}
          <ul className="pf-meta-list" style={{ marginTop: '0.85rem' }}>
            <li>
              <span>{mt("主题")}</span>
              <span style={{ maxWidth: '55%', textAlign: 'right' }}>
                {(project?.source_text || '').slice(0, 40)}
              </span>
            </li>
            <li>
              <span>{mt("时长")}</span>
              <span>{mt("~1–3 分钟")}</span>
            </li>
            <li>
              <span>{mt("分镜数")}</span>
              <span>{mt("AI 自动")}</span>
            </li>
          </ul>
          <button type="button" className="pf-btn pf-btn-ghost pf-btn-block pf-btn-sm" disabled>{mt("预览模板")}<ComingSoon />
          </button>
        </aside>

        <section className="pf-create-col">
          <div className="pf-style-block">
            <h3>{mt("画面风格")}</h3>
            <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0 0 0.65rem' }}>{mt("已由选题时选择的模板锁定，出图与出视频会自动带上画风。是否出角色由模板规则和主题让 AI 决定，不必再选一套人设。")}</p>
            {currentTpl ? (
              <div
                className={[
                  'pf-style-opt',
                  'selected',
                  isPortraitRatio(currentTpl.default_ratio) ? 'portrait' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                style={{ maxWidth: 280, textAlign: 'left' }}
              >
                <span className="pf-style-opt-media">
                  <img src={api.assetUrl(currentTpl.preview_cover)} alt="" />
                  {currentTpl.default_ratio ? (
                    <span className="pf-style-opt-ratio">{currentTpl.default_ratio}</span>
                  ) : null}
                </span>
                <div className="cap">{currentTpl.name}</div>
                <div className="cap-sub">{mt("模板画风")}</div>
              </div>
            ) : null}
            <label className="pf-field" style={{ marginTop: '0.75rem' }}>
              <span className="pf-field-label">{mt("风格提示词（可选覆盖）")}</span>
              <textarea
                className="pf-field-input"
                value={stylePrompt}
                onChange={(e) => setStylePrompt(e.target.value)}
                rows={2}
                style={{ resize: 'vertical', minHeight: 64 }}
              />
            </label>
          </div>

          <div className="pf-style-block">
            <h3>{mt("配音音色")}<button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" disabled>{mt("更多音色")}<ComingSoon />
              </button>
            </h3>
            <div className="pf-voice-row">
              {voices.map((v) => {
                const vid = voiceKey(v)
                const selected = voiceId === vid
                const loading = previewBusy === vid
                const playing = playingId === vid
                return (
                  <div
                    key={v.id}
                    className={selected ? 'pf-voice-card selected' : 'pf-voice-card'}
                    role="button"
                    tabIndex={0}
                    onClick={() => selectVoice(v)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        selectVoice(v)
                      }
                    }}
                  >
                    <strong className="pf-voice-name">{v.label}</strong>
                    <span className="pf-voice-meta">
                      {v.gender === 'female' ? mt("女声") : v.gender === 'male' ? mt("男声") : v.gender}
                    </span>
                    <button
                      type="button"
                      className={[
                        'pf-btn',
                        'pf-btn-sm',
                        'pf-btn-icon',
                        playing ? 'pf-btn-lime' : 'pf-btn-ghost',
                        'pf-voice-preview',
                      ].join(' ')}
                      disabled={loading || busy}
                      onClick={(e) => previewVoice(v, e)}
                    >
                      {loading ? (
                        mt("生成中…")
                      ) : playing ? (
                        mt("播放中")
                      ) : (
                        <>
                          <IconPlay size={12} />{mt("试听")}</>
                      )}
                    </button>
                  </div>
                )
              })}
            </div>
            {selectedVoice ? (
              <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0.55rem 0 0' }}>
                {mt("当前：{0} · 成片用该音色整片配音；点击「试听」可听约 5 秒样例", [selectedVoice.label])}
              </p>
            ) : null}
          </div>

          <div className="pf-style-block">
            <h3>{mt("成片方式")}</h3>
            <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0 0 0.65rem' }}>{mt("任意模板都可选择是否生成 AI 视频，与画幅无关。")}</p>
            <div className="pf-style-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
              {OUTPUT_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={pipelineMode === m.id ? 'pf-style-opt selected' : 'pf-style-opt'}
                  onClick={() => setPipelineMode(m.id)}
                >
                  <img src={m.image} alt="" />
                  <div className="cap">{mt(m.label)}</div>
                  <div className="cap-sub">{mt(m.desc)}</div>
                </button>
              ))}
            </div>
          </div>

          {mediaCatalog ? (
            <div className="pf-style-block">
              <h3>{mt("图片模型")}</h3>
              <label>{mt("分辨率")}<select value={imageResolution} onChange={event => setImageResolution(event.target.value)}>
                {(mediaCatalog.image_models.find(item => item.id === imageModel)?.available_resolutions ?? mediaCatalog.image_models.find(item => item.id === imageModel)?.allowed_resolutions ?? []).map(value => <option key={value} value={value}>{value}</option>)}
              </select></label>
              <MediaCostNotice modelId={imageModel} resolution={imageResolution} />
              <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0 0 0.65rem' }}>{mt("使用管理后台「模型」中已勾选的 TokenFree 模型。")}</p>
              <div className="pf-model-grid">
                {mediaCatalog.image_models.map((m: MediaModelOption) => (
                  <button
                    key={m.id}
                    type="button"
                    className={imageModel === m.id ? 'pf-model-opt selected' : 'pf-model-opt'}
                    disabled={m.available === false}
                    onClick={() => setImageModel(m.id)}
                  >
                    <div className="pf-model-opt-title">
                      <span>{mt(m.label)}</span>
                      {m.recommended ? <span className="pf-model-badge">{mt("推荐")}</span> : null}
                    </div>
                    <div className="pf-model-opt-desc">{m.description}</div>
                    <div className="pf-model-opt-provider">{Object.entries(m.prices ?? {}).map(([resolution, price]) => mt("{0} ¥{1}/张", [resolution, price])).join(' · ') || m.pricing_hint}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {mediaCatalog && pipelineMode === 'full' ? (
            <div className="pf-style-block">
              <h3>{mt("视频模型")}</h3>
              <label>{mt("分辨率")}<select value={videoResolution} onChange={event => setVideoResolution(event.target.value)}>
                {(mediaCatalog.video_models.find(item => item.id === videoModel)?.available_resolutions ?? mediaCatalog.video_models.find(item => item.id === videoModel)?.allowed_resolutions ?? []).map(value => <option key={value} value={value}>{value}</option>)}
              </select></label>
              <MediaCostNotice modelId={videoModel} resolution={videoResolution} seconds={1} />
              <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0 0 0.65rem' }}>{mt("图生视频所用模型；静图成片模式不调用。")}</p>
              <div className="pf-model-grid">
                {mediaCatalog.video_models.map((m: MediaModelOption) => (
                  <button
                    key={m.id}
                    type="button"
                    className={videoModel === m.id ? 'pf-model-opt selected' : 'pf-model-opt'}
                    disabled={m.available === false}
                    onClick={() => setVideoModel(m.id)}
                  >
                    <div className="pf-model-opt-title">
                      <span>{mt(m.label)}</span>
                      {m.recommended ? <span className="pf-model-badge">{mt("推荐")}</span> : null}
                    </div>
                    <div className="pf-model-opt-desc">{m.description}</div>
                    <div className="pf-model-opt-provider">{Object.entries(m.prices ?? {}).map(([resolution, price]) => mt("{0} ¥{1}/秒", [resolution, price])).join(' · ') || m.pricing_hint}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="pf-style-block">
            <h3>{mt("输出比例")}</h3>
            <div className="pf-ratio-row">
              {RATIOS.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className={ratio === r.id ? 'pf-ratio selected' : 'pf-ratio'}
                  onClick={() => pickRatio(r)}
                >
                  <div className="box" style={{ width: r.w, height: r.h }} />
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        <aside className="pf-create-col">
          <h3>{mt("实时预览")}</h3>
          <div
            className={[
              'pf-editor-preview',
              isPortraitRatio(ratio) ? 'portrait' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            style={{ marginBottom: '0.85rem' }}
          >
            {currentTpl ? (
              <img src={api.assetUrl(currentTpl.preview_cover)} alt="" />
            ) : (
              <span className="empty">{mt("预览占位")}</span>
            )}
          </div>
          <p className="pf-muted" style={{ fontSize: '0.8rem' }}>{mt("生成后可在分镜台查看真实画面。当前为模板预览。")}</p>
          <h3 style={{ marginTop: '1rem' }}>{mt("当前配置概览")}</h3>
          <ul className="pf-meta-list">
            <li>
              <span>{mt("风格")}</span>
              <span>{currentTpl?.name || '—'}</span>
            </li>
            <li>
              <span>{mt("角色")}</span>
              <span>{mt("AI 按模板与主题决定")}</span>
            </li>
            <li>
              <span>{mt("配音")}</span>
              <span>{selectedVoice?.label || mt("默认")}</span>
            </li>
            <li>
              <span>{mt("比例")}</span>
              <span>{ratio}</span>
            </li>
            <li>
              <span>{mt("成片")}</span>
              <span>{pipelineMode === 'image_text' ? mt("静图成片") : mt("AI 视频")}</span>
            </li>
          </ul>
          {selectedVoice ? (
            <button
              type="button"
              className="pf-btn pf-btn-ghost pf-btn-block pf-btn-sm pf-btn-icon"
              style={{ marginTop: '0.75rem' }}
              disabled={busy || previewBusy === voiceKey(selectedVoice)}
              onClick={(e) => previewVoice(selectedVoice, e)}
            >
              <IconPlay size={14} />
              {playingId === voiceKey(selectedVoice)
                ? mt("停止试听")
                : mt("试听「{0}」", [selectedVoice.label])}
            </button>
          ) : null}
          {error ? <BillingErrorNotice message={mt(error)} style={{ marginTop: '0.75rem' }} /> : null}
          <button
            type="button"
            className="pf-btn pf-btn-lime pf-btn-block pf-btn-lg pf-btn-icon"
            style={{ marginTop: '0.75rem' }}
            disabled={busy || Boolean(previewBusy)}
            onClick={generate}
          >
            {busy ? mt("启动中…") : project.shots?.length ? mt("保存并继续") : mt("生成故事板")}
            {!busy ? <span aria-hidden>→</span> : null}
          </button>
          <p className="pf-muted" style={{ fontSize: '0.78rem', marginTop: '0.5rem' }}>{mt("先生成分镜脚本，确认修改后再手动开始出图与配音。")}</p>
        </aside>
      </div>
    </AppShell>
  )
}
