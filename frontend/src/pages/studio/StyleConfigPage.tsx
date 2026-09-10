import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, defaultsFromTemplate } from '../../api'
import type { PipelineMode, Project, Template, VoicePreset } from '../../api'
import AppShell from '../../components/layout/AppShell'
import Stepper from '../../components/ui/Stepper'
import ComingSoon from '../../components/ui/ComingSoon'
import { IconChevronLeft, IconPlay } from '../../components/ui/Icons'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import { handleBillingError } from '../../lib/billingError'
import { CREATE_STEPS } from '../../lib/status'

const CHAR_PRESETS = [
  {
    id: 'real',
    label: '写实人物',
    desc: '真实人物质感',
    image: '/char-presets/real.jpg',
    promptHint: '写实人物操作电脑或系统界面，侧脸或过肩视角，手部与屏幕清晰',
  },
  {
    id: 'anime',
    label: '动漫角色',
    desc: '二次元形象',
    image: '/char-presets/anime.jpg',
    promptHint: '动漫风格角色在工位前操作系统，造型简洁统一',
  },
  {
    id: 'sil',
    label: '剪影',
    desc: '抽象剪影表达',
    image: '/char-presets/sil.jpg',
    promptHint: '剪影人物操作系统界面，抽象轮廓，信息层级清晰',
  },
  {
    id: 'none',
    label: '无角色',
    desc: '纯场景解说',
    image: '/char-presets/none.jpg',
    promptHint: '无人物角色，专注产品界面、文档与架构示意',
  },
]

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
function isPortraitRatio(ratio: string | undefined | null): boolean {
  const raw = String(ratio || '').trim()
  const m = raw.match(/^(\d+(?:\.\d+)?)\s*[:/x]\s*(\d+(?:\.\d+)?)$/i)
  if (!m) return false
  return Number(m[2]) > Number(m[1])
}

export default function StyleConfigPage() {
  const { id } = useParams()
  const projectId = Number(id)
  const nav = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [voices, setVoices] = useState<VoicePreset[]>([])
  const [stylePrompt, setStylePrompt] = useState('')
  const [characterPrompt, setCharacterPrompt] = useState('')
  const [extraPrompt, setExtraPrompt] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [pipelineMode, setPipelineMode] = useState<PipelineMode>('full')
  const [ratio, setRatio] = useState('16:9')
  const [charPreset, setCharPreset] = useState('real')
  const [busy, setBusy] = useState(false)
  const [previewBusy, setPreviewBusy] = useState<string | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    if (!projectId) {
      nav('/studio/new')
    }
    api.templates().then(setTemplates)
    api.voices().then(setVoices)
    api
      .getProject(projectId)
      .then((p) => {
        setProject(p)
        setStylePrompt(p.style_prompt || '')
        setCharacterPrompt(p.character_prompt || '')
        setExtraPrompt(p.extra_prompt || '')
        setVoiceId(p.voice_id || '')
        setPipelineMode(p.pipeline_mode || 'full')
        setRatio(p.output_ratio || (p.pipeline_mode === 'image_text' ? '9:16' : '16:9'))
      })
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
  }, [nav, projectId])

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
      audioRef.current = null
    }
  }, [])

  const currentTpl = useMemo(
    () => templates.find((t) => t.id === project?.template_id),
    [templates, project?.template_id],
  )

  const styleOptions = useMemo(() => templates.slice(0, 6), [templates])
  const selectedVoice = voices.find((v) => v.speaker === voiceId || v.id === voiceId)

  useEffect(() => {
    if (!project || !currentTpl) return
    if (!stylePrompt && !characterPrompt) {
      const d = defaultsFromTemplate(currentTpl)
      setStylePrompt((v) => v || d.style_prompt)
      setCharacterPrompt((v) => v || d.character_prompt)
      setExtraPrompt((v) => v || d.extra_prompt)
      setVoiceId((v) => v || d.voice_id)
    }
  }, [project, currentTpl])

  useEffect(() => {
    if (!project || project.output_ratio || !currentTpl?.default_ratio) return
    setRatio(currentTpl.default_ratio)
  }, [project?.id, project?.output_ratio, currentTpl?.default_ratio])

  function pickStyle(t: Template) {
    const d = defaultsFromTemplate(t)
    setStylePrompt(d.style_prompt)
    setCharacterPrompt(d.character_prompt)
    setExtraPrompt(d.extra_prompt)
    setVoiceId(d.voice_id)
    // 风格带默认画幅；用户仍可在下方「输出比例」改
    if (d.output_ratio) setRatio(d.output_ratio)
    if (/无人物|无角色/.test(d.character_prompt)) setCharPreset('none')
    else if (/剪影/.test(d.character_prompt)) setCharPreset('sil')
    else if (/动漫|二次元/.test(d.character_prompt)) setCharPreset('anime')
    else setCharPreset('real')
    if (project) {
      api
        .updateProject(project.id, {
          template_id: t.id,
          voice_id: d.voice_id,
          output_ratio: d.output_ratio || undefined,
        })
        .then(setProject)
        .catch((err) => setError(err instanceof Error ? err.message : '更新失败'))
    }
  }

  function pickRatio(r: (typeof RATIOS)[0]) {
    setRatio(r.id)
  }

  function stopPreview() {
    audioRef.current?.pause()
    audioRef.current = null
    setPlayingId(null)
  }

  async function previewVoice(v: VoicePreset, e: MouseEvent) {
    e.stopPropagation()
    const vid = v.speaker || v.id
    setVoiceId(vid)
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
    stopPreview()
    setBusy(true)
    setError('')
    try {
      const charNote =
        charPreset === 'none'
          ? '无人物角色，侧重场景与信息图表。'
          : charPreset === 'anime'
            ? '角色偏动漫造型。'
            : charPreset === 'sil'
              ? '角色以剪影呈现。'
              : ''
      const d = currentTpl ? defaultsFromTemplate(currentTpl) : null
      /*
       * styleOut 风格提示词；与模板相同则留空，生成时读后台
       * extraOut 额外提示词
       * charText 角色描述原文；与模板相同则不写入覆盖
       */
      const styleOut = stylePrompt.trim()
      const extraOut = extraPrompt.trim()
      const charText = characterPrompt.trim()
      const sameStyle = Boolean(d) && styleOut === d!.style_prompt
      const sameChar = Boolean(d) && charText === d!.character_prompt
      const sameExtra = Boolean(d) && extraOut === d!.extra_prompt
      await api.updateProject(project.id, {
        style_prompt: sameStyle ? '' : styleOut,
        character_prompt: sameChar ? '' : [charText, charNote].filter(Boolean).join('\n'),
        extra_prompt: sameExtra ? '' : extraOut,
        voice_id: voiceId,
        pipeline_mode: pipelineMode,
        output_ratio: ratio,
      })
      const started = await api.generate(project.id)
      nav(`/studio/${started.id}`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '生成失败'
      setError(msg)
      await handleBillingError(err, nav)
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

  return (
    <AppShell active="studio" wide>
      <header className="pf-page-head">
        <div className="pf-page-head-row">
          <div>
            <button type="button" className="pf-back" onClick={() => nav('/studio/new')}>
              <IconChevronLeft size={18} />
              返回创作台
            </button>
            <h1 className="pf-page-title">{project?.title || '风格配置'}</h1>
          </div>
          <Stepper steps={CREATE_STEPS} current={2} doneThrough={1} />
        </div>
      </header>

      <div className="pf-style-layout">
        <aside className="pf-create-col">
          <h3>项目信息</h3>
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
              <span>主题</span>
              <span style={{ maxWidth: '55%', textAlign: 'right' }}>
                {(project?.source_text || '').slice(0, 40)}
              </span>
            </li>
            <li>
              <span>时长</span>
              <span>~1–3 分钟</span>
            </li>
            <li>
              <span>分镜数</span>
              <span>AI 自动</span>
            </li>
          </ul>
          <button type="button" className="pf-btn pf-btn-ghost pf-btn-block pf-btn-sm" disabled>
            预览模板 <ComingSoon />
          </button>
        </aside>

        <section className="pf-create-col">
          <div className="pf-style-block">
            <h3>
              画面风格
              <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" disabled>
                更多风格 <ComingSoon />
              </button>
            </h3>
            <div className="pf-style-grid">
              {styleOptions.map((t) => {
                const portrait = isPortraitRatio(t.default_ratio)
                return (
                  <button
                    key={t.id}
                    type="button"
                    className={[
                      'pf-style-opt',
                      portrait ? 'portrait' : '',
                      project?.template_id === t.id ? 'selected' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => pickStyle(t)}
                  >
                    <span className="pf-style-opt-media">
                      <img src={api.assetUrl(t.preview_cover)} alt="" />
                      {t.default_ratio ? (
                        <span className="pf-style-opt-ratio">{t.default_ratio}</span>
                      ) : null}
                    </span>
                    <div className="cap">{t.name}</div>
                  </button>
                )
              })}
            </div>
            <label className="pf-field" style={{ marginTop: '0.75rem' }}>
              <span className="pf-field-label">风格提示词</span>
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
            <h3>角色设定</h3>
            <div className="pf-style-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
              {CHAR_PRESETS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={charPreset === c.id ? 'pf-style-opt selected' : 'pf-style-opt'}
                  onClick={() => {
                    setCharPreset(c.id)
                    setCharacterPrompt(c.promptHint)
                  }}
                >
                  <img src={c.image} alt="" />
                  <div className="cap">{c.label}</div>
                  <div className="cap-sub">{c.desc}</div>
                </button>
              ))}
            </div>
            <label className="pf-field" style={{ marginTop: '0.75rem' }}>
              <span className="pf-field-label">角色描述</span>
              <textarea
                className="pf-field-input"
                value={characterPrompt}
                onChange={(e) => setCharacterPrompt(e.target.value)}
                rows={2}
                style={{ resize: 'vertical', minHeight: 64 }}
              />
            </label>
          </div>

          <div className="pf-style-block">
            <h3>
              配音音色
              <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" disabled>
                更多音色 <ComingSoon />
              </button>
            </h3>
            <div className="pf-voice-row">
              {voices.map((v) => {
                const vid = v.speaker || v.id
                const selected = voiceId === vid
                const loading = previewBusy === vid
                const playing = playingId === vid
                return (
                  <div
                    key={v.id}
                    className={selected ? 'pf-voice-card selected' : 'pf-voice-card'}
                    role="button"
                    tabIndex={0}
                    onClick={() => setVoiceId(vid)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setVoiceId(vid)
                      }
                    }}
                  >
                    <strong className="pf-voice-name">{v.label}</strong>
                    <span className="pf-voice-meta">
                      {v.gender === 'female' ? '女声' : v.gender === 'male' ? '男声' : v.gender}
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
                        '生成中…'
                      ) : playing ? (
                        '播放中'
                      ) : (
                        <>
                          <IconPlay size={12} />
                          试听
                        </>
                      )}
                    </button>
                  </div>
                )
              })}
            </div>
            {selectedVoice ? (
              <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0.55rem 0 0' }}>
                当前：{selectedVoice.label} · 点击「试听」可听约 5 秒样例
              </p>
            ) : null}
          </div>

          <div className="pf-style-block">
            <h3>
              背景音乐 <ComingSoon />
            </h3>
            <div className="pf-bgm-card">
              <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm pf-btn-icon" disabled>
                <IconPlay size={14} />
              </button>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong style={{ fontSize: '0.9rem' }}>星际远航</strong>
                <div className="pf-bgm-wave" />
              </div>
              <span className="pf-muted">02:28</span>
            </div>
          </div>

          <div className="pf-style-block">
            <h3>
              字幕样式 <ComingSoon />
            </h3>
            <div className="pf-hint">字体、字号、对齐与颜色工具条将在成片编辑器中提供。</div>
          </div>

          <div className="pf-style-block">
            <h3>成片方式</h3>
            <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0 0 0.65rem' }}>
              任意模板都可选择是否生成 AI 视频，与画幅无关。
            </p>
            <div className="pf-style-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
              {OUTPUT_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={pipelineMode === m.id ? 'pf-style-opt selected' : 'pf-style-opt'}
                  onClick={() => setPipelineMode(m.id)}
                >
                  <img src={m.image} alt="" />
                  <div className="cap">{m.label}</div>
                  <div className="cap-sub">{m.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="pf-style-block">
            <h3>输出比例</h3>
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
          <h3>实时预览</h3>
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
              <span className="empty">预览占位</span>
            )}
          </div>
          <p className="pf-muted" style={{ fontSize: '0.8rem' }}>
            生成后可在分镜台查看真实画面。当前为模板预览。
          </p>
          <h3 style={{ marginTop: '1rem' }}>当前配置概览</h3>
          <ul className="pf-meta-list">
            <li>
              <span>风格</span>
              <span>{currentTpl?.name || '—'}</span>
            </li>
            <li>
              <span>角色</span>
              <span>{CHAR_PRESETS.find((c) => c.id === charPreset)?.label}</span>
            </li>
            <li>
              <span>配音</span>
              <span>{selectedVoice?.label || '默认'}</span>
            </li>
            <li>
              <span>比例</span>
              <span>{ratio}</span>
            </li>
            <li>
              <span>成片</span>
              <span>{pipelineMode === 'image_text' ? '静图成片' : 'AI 视频'}</span>
            </li>
          </ul>
          {selectedVoice ? (
            <button
              type="button"
              className="pf-btn pf-btn-ghost pf-btn-block pf-btn-sm pf-btn-icon"
              style={{ marginTop: '0.75rem' }}
              disabled={busy || previewBusy === (selectedVoice.speaker || selectedVoice.id)}
              onClick={(e) => previewVoice(selectedVoice, e)}
            >
              <IconPlay size={14} />
              {playingId === (selectedVoice.speaker || selectedVoice.id)
                ? '停止试听'
                : `试听「${selectedVoice.label}」`}
            </button>
          ) : null}
          {error ? <BillingErrorNotice message={error} style={{ marginTop: '0.75rem' }} /> : null}
          <button
            type="button"
            className="pf-btn pf-btn-lime pf-btn-block pf-btn-lg pf-btn-icon"
            style={{ marginTop: '0.75rem' }}
            disabled={busy || Boolean(previewBusy)}
            onClick={generate}
          >
            {busy ? '启动中…' : '生成故事板'}
            {!busy ? <span aria-hidden>→</span> : null}
          </button>
          <p className="pf-muted" style={{ fontSize: '0.78rem', marginTop: '0.5rem' }}>
            先生成分镜脚本，确认修改后再手动开始出图与配音。
          </p>
        </aside>
      </div>
    </AppShell>
  )
}
