/** 画布视频节点：风格 / Seedance 模型 / 时长 / 比例清晰度 */
import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { BarChart3, ChevronDown, RectangleVertical, Smile, Timer } from 'lucide-react'
import {
  getImageStyleLabel,
  IMAGE_STYLE_OPTIONS,
} from '../../../../lib/dramaImageStyles'
import { DramaImageStylePreviewImg } from '../../../../components/drama/DramaImageStylePreviewImg'
import {
  clampVideoDuration,
  formatVideoOutputLabel,
  getVideoModelLabel,
  VIDEO_ASPECT_RATIO_OPTIONS,
  VIDEO_DURATION_MAX,
  VIDEO_DURATION_MIN,
  VIDEO_DURATION_PRESETS,
  VIDEO_GENERATION_MODELS,
  VIDEO_RESOLUTION_OPTIONS,
  type VideoAspectRatio,
  type VideoGenerationModelId,
  type VideoGenerationOptions,
  type VideoResolution,
} from '../../../../lib/dramaVideoGenerationOptions'
import './dramaImageGenOptions.css'

type DramaVideoGenOptionsBarProps = {
  value: VideoGenerationOptions
  onChange: (next: VideoGenerationOptions) => void
  disabled?: boolean
}

type OpenPanel = 'style' | 'model' | 'duration' | 'output' | null

/** 渲染视频生成选项条 */
export function DramaVideoGenOptionsBar({
  value,
  onChange,
  disabled = false,
}: DramaVideoGenOptionsBarProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState<OpenPanel>(null)

  useEffect(() => {
    if (!open) return
    function onDoc(e: Event) {
      const target = e.target as Node | null
      if (rootRef.current && target && !rootRef.current.contains(target)) {
        setOpen(null)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const stop = (e: MouseEvent) => {
    e.stopPropagation()
  }

  const styleLabel = getImageStyleLabel(value.image_style_id) || '风格'
  const modelLabel = getVideoModelLabel(value.model_id)
  const outputLabel = formatVideoOutputLabel(value.aspect_ratio, value.resolution)

  return (
    <div ref={rootRef} className="fc-gen-opts" onMouseDown={stop} onPointerDown={stop}>
      <div className="fc-gen-opts-triggers">
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'style' || value.image_style_id ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'style' ? null : 'style'))}
        >
          <Smile size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{styleLabel}</span>
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'model' ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'model' ? null : 'model'))}
        >
          <BarChart3 size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{modelLabel}</span>
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'duration' ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'duration' ? null : 'duration'))}
        >
          <Timer size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{value.duration_sec}s</span>
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'output' ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'output' ? null : 'output'))}
        >
          <RectangleVertical size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{outputLabel}</span>
          <ChevronDown size={12} />
        </button>
      </div>

      {open === 'style' ? (
        <div className="fc-gen-opt-panel fc-gen-style-panel" role="dialog" aria-label="视频风格">
          <div className="fc-gen-opt-panel-title">视频风格</div>
          <div className="fc-gen-style-grid">
            {IMAGE_STYLE_OPTIONS.map((opt) => {
              const selected = value.image_style_id === opt.id
              return (
                <button
                  key={opt.id}
                  type="button"
                  className={`fc-gen-style-card${selected ? ' selected' : ''}`}
                  onClick={() => {
                    onChange({ ...value, image_style_id: opt.id })
                    setOpen(null)
                  }}
                >
                  <DramaImageStylePreviewImg styleId={opt.id} alt={opt.label} loading="lazy" />
                  <span>{opt.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      ) : null}

      {open === 'model' ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="视频模型">
          <div className="fc-gen-opt-panel-title">模型</div>
          <div className="fc-gen-model-list">
            {VIDEO_GENERATION_MODELS.map((m) => (
              <button
                key={m.id}
                type="button"
                className={`fc-gen-model-item${value.model_id === m.id ? ' selected' : ''}`}
                onClick={() => {
                  onChange({ ...value, model_id: m.id as VideoGenerationModelId })
                  setOpen(null)
                }}
              >
                <strong>{m.label}</strong>
                <span>{m.description}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {open === 'duration' ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="视频时长">
          <div className="fc-gen-opt-panel-title">时长</div>
          <div className="fc-gen-chip-row">
            {VIDEO_DURATION_PRESETS.map((sec) => (
              <button
                key={sec}
                type="button"
                className={`fc-gen-chip${value.duration_sec === sec ? ' selected' : ''}`}
                onClick={() => {
                  onChange({ ...value, duration_sec: sec })
                  setOpen(null)
                }}
              >
                {sec}s
              </button>
            ))}
          </div>
          <label className="fc-gen-duration-custom">
            自定义（{VIDEO_DURATION_MIN}–{VIDEO_DURATION_MAX}s）
            <input
              type="number"
              min={VIDEO_DURATION_MIN}
              max={VIDEO_DURATION_MAX}
              value={value.duration_sec}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...value, duration_sec: clampVideoDuration(Number(e.target.value)) })
              }
            />
          </label>
        </div>
      ) : null}

      {open === 'output' ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="画幅与清晰度">
          <div className="fc-gen-opt-panel-title">比例</div>
          <div className="fc-gen-chip-row">
            {VIDEO_ASPECT_RATIO_OPTIONS.map((ratio) => (
              <button
                key={ratio}
                type="button"
                className={`fc-gen-chip${value.aspect_ratio === ratio ? ' selected' : ''}`}
                onClick={() => onChange({ ...value, aspect_ratio: ratio as VideoAspectRatio })}
              >
                {ratio}
              </button>
            ))}
          </div>
          <div className="fc-gen-opt-panel-title" style={{ marginTop: 10 }}>
            清晰度
          </div>
          <div className="fc-gen-chip-row">
            {VIDEO_RESOLUTION_OPTIONS.map((res) => (
              <button
                key={res}
                type="button"
                className={`fc-gen-chip${value.resolution === res ? ' selected' : ''}`}
                onClick={() => {
                  onChange({ ...value, resolution: res as VideoResolution })
                  setOpen(null)
                }}
              >
                {res}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
