import { StudioModelSelect } from '../StudioModelSelect'
import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Camera, Eye, FileText, Film, Image as ImageIcon, Mic, Plus, PersonStanding, Sparkles, X } from 'lucide-react'
import { ComposerMenu, ComposerSelect } from './ComposerMenu'
import { PromptInput } from './PromptInput'
import { mentionQuery, mentionToken, promptCaret } from './promptMentions'
import type { StudioVideoMode } from './generationReferences'
import type { ComposerMention } from './studioNodeContext'
import { generationControls, type GenerationControls } from './generationControls'

export type ComposerAction = 'edit' | 'crop' | 'video' | 'reference' | 'audio' | 'inpaint' | 'outpaint' | 'compose'

type Chip = { id: string; label: string }
type ModelOption = { id: string; label: string }

type Props = {
  action: ComposerAction
  prompt: string
  onPrompt: (value: string) => void
  chips: Chip[]
  onRemoveChip: (id: string) => void
  onAddChip: (chip: Chip, append: string) => void
  refs: { id: string; url: string; label: string; mediaKind?: string; status?: string }[]
  onRemoveRef: (id: string) => void
  onFocusRef?: (id: string) => void
  onAddRef: () => void
  mentions: { connected: ComposerMention[]; canvas: ComposerMention[]; assets: ComposerMention[] }
  onMention: (item: ComposerMention) => void
  modelId: string
  modelOptions: ModelOption[]
  onModelChange: (id: string) => void
  ratio: string
  onRatioChange: (value: string) => void
  count: string
  onCountChange: (value: string) => void
  resolution: string
  onResolutionChange: (value: string) => void
  duration: string
  onDurationChange: (value: string) => void
  estimate: string
  videoMode?: StudioVideoMode
  onVideoModeChange?: (value: StudioVideoMode) => void
  videoModeOptions?: { id: string; label: string; disabled?: boolean; hint?: string }[]
  validationMessage?: string
  generateAudio?: boolean
  onAudioChange?: (value: boolean) => void
  isVideo: boolean
  controls?: GenerationControls
  voice?: string
  onVoiceChange?: (value: string) => void
  onClose: () => void
  onSubmit: () => void
  canSubmit: boolean
  /** 挂在节点下槽时使用节点附样式（对照 Toonflow / Paba promptCard）。 */
  attached?: boolean
}

const CASES = [
  { id: 'case-q', label: '案例·Q版', text: '高质量 3D 卡通电影风格，Q 版大头身比例，柔和棚拍光。' },
  { id: 'case-cinematic', label: '案例·电影感', text: '电影级光影，浅景深，胶片颗粒，写实人像。' },
  { id: 'case-product', label: '案例·产品', text: '干净棚拍产品图，柔光箱补光，纯色背景，细节清晰。' },
]

const PRESETS = {
  案例: CASES,
  姿势: [{ id: 'pose-standing', label: '自然站姿', text: '人物自然站立，重心放松，双手自然垂放，保持身体比例准确。' }, { id: 'pose-seated', label: '侧身坐姿', text: '人物侧身坐在椅子上，双腿自然摆放，回头看向镜头。' }, { id: 'pose-walking', label: '向前行走', text: '人物向前自然行走，步态轻松，双臂随步伐自然摆动。' }],
  运镜: [{ id: 'camera-push', label: '缓慢推进', text: '镜头平稳缓慢推进，从中景过渡到近景，始终对焦主体。' }, { id: 'camera-orbit', label: '环绕主体', text: '镜头围绕主体平稳环绕，主体保持画面中心，运动连续自然。' }, { id: 'camera-fixed', label: '固定机位', text: '固定机位拍摄，保持构图稳定，无推拉摇移。' }],
  特效: [{ id: 'effect-particles', label: '漂浮光点', text: '细小柔和光点在空气中缓缓漂浮，与场景光照自然融合。' }, { id: 'effect-rain', label: '雨幕氛围', text: '细雨缓缓落下，地面出现自然雨水反光，保持主体清晰。' }, { id: 'effect-slow', label: '慢动作', text: '使用流畅的慢动作展现主体运动，细节清晰，运动轨迹自然。' }],
}
const COUNTS = ['1', '2', '4']

function ReferenceThumb({ item }: { item: { url?: string; mediaKind?: string } }) {
  return item.mediaKind === 'text' ? <FileText size={14} /> : item.mediaKind === 'audio' ? <Mic size={14} /> : item.url ? item.mediaKind === 'video' ? <video src={item.url} muted preload="metadata" /> : <img src={item.url} alt="" /> : item.mediaKind==='video' ? <Film size={14}/> : <ImageIcon size={14} />
}

/** Paba 图片节点生成面板：参考图 / 案例 + 提示词 + 模型 / 比例 / 张数。 */
/** 从光标前取出尚未结束的 @ 查询。 */
/** @ 引用菜单：已接入、画布上、素材库。 */
export function MentionMenu({ query, mentions, onPick, onLibrary }: {
  query: string
  mentions: { connected: ComposerMention[]; canvas: ComposerMention[]; assets: ComposerMention[] }
  onPick: (item: ComposerMention) => void
  onLibrary: () => void
}) {
  const match = (item: ComposerMention) => !query || `${item.label} ${item.hint || ''}`.toLowerCase().includes(query.toLowerCase())
  const groups = [
    { title: '已接入', items: mentions.connected.filter(match) },
    { title: '画布上', items: mentions.canvas.filter(match) },
    { title: '素材库', items: mentions.assets.filter(match) },
  ].filter((group) => group.items.length)
  return <div className="pf-mention" role="listbox">
    {!groups.length && <p>没有可引用的素材</p>}
    {groups.map((group) => <section key={group.title}>
      <h4>{group.title}</h4>
      {group.items.map((item) => <button type="button" key={`${item.source}-${item.id}`} onMouseDown={(event) => event.preventDefault()} onClick={() => onPick(item)}>
        <span className="pf-mention-thumb"><ReferenceThumb item={item} /></span>
        <b>{item.label}</b>
        <small>{item.hint || (item.source === 'asset' ? '素材' : '图片')}</small>
      </button>)}
    </section>)}
    <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={onLibrary}>从素材库选择</button>
  </div>
}

export function PromptComposer({
  action, prompt, onPrompt, chips, onRemoveChip, onAddChip, refs, onFocusRef, onRemoveRef, onAddRef, mentions, onMention,
  modelId, modelOptions, onModelChange, ratio, onRatioChange, count, onCountChange,
  resolution, onResolutionChange, duration, onDurationChange, estimate, isVideo, onClose, onSubmit, canSubmit, attached, controls, voice, onVoiceChange, videoMode, onVideoModeChange, videoModeOptions, validationMessage, generateAudio, onAudioChange,
}: Props) {
  const choices = controls || generationControls(undefined, isVideo)
  const [presetMenu, setPresetMenu] = useState<keyof typeof PRESETS | null>(null)
  const imageMode = !isVideo && action !== 'audio' && action !== 'crop'
  const placeholder = action === 'audio' ? '输入要读出来的台词' : imageMode
    ? '描述画面内容与风格，输入 @ 引用参考图'
    : '描述你想要生成的画面、动作和声音，输入 @ 引用素材'
  const inputRef = useRef<HTMLDivElement | null>(null)
  const [mentionAt, setMentionAt] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelBlur = () => { if (blurTimer.current !== null) { clearTimeout(blurTimer.current); blurTimer.current = null } }
  useEffect(() => () => cancelBlur(), [])
  const syncMention = (value: string, caret: number) => {
    const next = mentionQuery(value, caret)
    setQuery(next || '')
    setMentionAt(next === null ? null : value.slice(0, caret).lastIndexOf('@'))
  }
  const pickMention = (item: ComposerMention) => {
    const caret = inputRef.current ? promptCaret(inputRef.current) : prompt.length
    const at = mentionAt ?? prompt.lastIndexOf('@')
    const chosen = { ...item, label: refs.find((ref) => ref.id === item.id)?.label || item.label }
    const token = mentionToken(chosen)
    const next = at >= 0 ? `${prompt.slice(0, at)}${token} ${prompt.slice(Math.max(caret, at))}` : `${prompt}${token} `
    onPrompt(next)
    onMention(chosen)
    setMentionAt(null)
  }

  return <div className={`pf-composer-card${attached ? ' is-attached' : ''}${imageMode ? ' is-image' : ''}`} onMouseDown={(event) => event.stopPropagation()}>
    <div className="pf-composer-tags">
      {chips.map((chip) => <span className="pf-chip" key={chip.id}>{chip.label}<button type="button" aria-label="移除标签" onClick={() => onRemoveChip(chip.id)}><X size={12} /></button></span>)}
      {refs.map((item) => <span className={`pf-chip is-ref${item.status?' is-pending':''}`} key={item.id} title={`${item.label}${item.status?' · '+item.status:''}`}><button type="button" className="pf-ref-jump" aria-label={`定位关联节点 ${item.label}`} onClick={()=>onFocusRef?.(item.id)}><ReferenceThumb item={item} /><span className="pf-ref-label">{item.label}</span></button><button type="button" aria-label="移除参考" onClick={() => onRemoveRef(item.id)}><X size={12} /></button></span>)}
      {action !== 'audio' && <button type="button" className="pf-chip-btn" onMouseDown={(event) => event.preventDefault()} onClick={() => { cancelBlur(); setMentionAt(prompt.length); setQuery(''); inputRef.current?.focus() }}><Plus size={13} /> {isVideo ? '参考' : '参考图'}</button>}
      {(imageMode || isVideo) && (isVideo ? (['特效', '运镜', '姿势', '案例'] as const) : (['姿势', '案例'] as const)).map((name) => <button type="button" key={name} className="pf-chip-btn" aria-expanded={presetMenu === name} onClick={() => setPresetMenu(presetMenu === name ? null : name)}>{name === '运镜' ? <Camera size={16} /> : name === '姿势' ? <PersonStanding size={16} /> : name === '特效' ? <Sparkles size={16} /> : <ImageIcon size={16} />}{name}</button>)}
      {!attached && <button type="button" className="pf-composer-close" aria-label="关闭" onClick={onClose}><X size={16} /></button>}
    </div>
    {presetMenu && <div className="pf-prompt-presets">{PRESETS[presetMenu].map((preset) => <button type="button" key={preset.id} onClick={() => { onAddChip(preset, preset.text); setPresetMenu(null) }}><b>{preset.label.replace('案例·', '')}</b><span>{preset.text}</span></button>)}</div>}
    <div className="pf-composer-input">
      <PromptInput inputRef={inputRef} value={prompt} label="生成描述" placeholder={placeholder} references={[...mentions.connected, ...mentions.canvas, ...mentions.assets]} onChange={(value, caret) => { onPrompt(value); syncMention(value, caret) }} onCaret={syncMention} onFocus={cancelBlur} onBlur={() => { cancelBlur(); blurTimer.current = setTimeout(() => setMentionAt(null), 120) }} />
      {mentionAt !== null ? <MentionMenu query={query} mentions={mentions} onPick={pickMention} onLibrary={() => { setMentionAt(null); onAddRef() }} /> : null}
    </div>
    {action === 'crop' && <div className="pf-crop-row"><button type="button" onClick={onSubmit}>按当前比例裁剪</button></div>}
    <footer>
      <div className="pf-composer-controls">
      {action !== 'crop' && action !== 'compose' && <StudioModelSelect label="模型" value={modelId} options={modelOptions.length ? modelOptions : [{ id: '', label: '默认模型' }]} onChange={onModelChange} />}
      {action === 'compose' ? <span>输入片段按连线顺序拼接，当前片段放在末尾</span> : action === 'audio' ? <ComposerSelect label="配音音色" value={voice || 'narrator_calm'} options={[{ id: 'narrator_calm', label: '沉稳旁白' }, { id: 'warm_storyteller', label: '温暖叙事' }, { id: 'teacher_clear', label: '清晰讲解' }]} onChange={(value) => onVoiceChange?.(value)} /> : isVideo ? <>
        <ComposerSelect label="视频生成方式" value={videoMode || 'text_to_video'} options={videoModeOptions || []} onChange={(value) => onVideoModeChange?.(value as StudioVideoMode)} />
        <ComposerMenu label="视频参数" value={`${ratio} · ${resolution} · ${duration} 秒`} wide>{() => <>
          <h3>视频参数</h3>
          {onAudioChange && <label className="pf-composer-audio"><input type="checkbox" checked={generateAudio !== false} onChange={event => onAudioChange(event.target.checked)} />生成声音（对白 / 环境声）</label>}
          {([{ name: '比例', value: ratio, values: choices.ratios, change: onRatioChange }, { name: '清晰度', value: resolution, values: choices.resolutions, change: onResolutionChange }, { name: '时长', value: duration, values: choices.durations, change: onDurationChange }]).map((field) => <fieldset key={field.name}><legend>{field.name}</legend><div className="pf-composer-option-grid">{field.values.map((value) => <button type="button" role="radio" aria-checked={value === field.value} key={value} onClick={() => field.change(value)}>{field.name === '比例' && <i className="pf-ratio-preview" style={{ aspectRatio: value.replace(':', '/') }} />}{value}{field.name === '时长' ? ' 秒' : ''}</button>)}</div></fieldset>)}
        </>}</ComposerMenu>
      </> : <>
        <ComposerSelect label="比例" value={ratio} options={choices.ratios.map((id) => ({ id, label: ({auto:'自动','1:1':'1:1 方形','3:2':'3:2 横版','2:3':'2:3 竖版'} as Record<string,string>)[id] || id }))} onChange={onRatioChange} />
        {action !== 'crop' && <><ComposerSelect label="清晰度" value={resolution} options={choices.resolutions.map((id) => ({ id, label: id }))} onChange={onResolutionChange} /><ComposerSelect label="张数" value={count} options={(action === 'inpaint' ? ['1'] : COUNTS).map((id) => ({ id, label: `${id} 张` }))} onChange={onCountChange} /></>}
      </>}
      <span className="pf-composer-spacer" />
      {!validationMessage && <span className="pf-composer-quote" title={estimate}><Eye size={15} /><em className="pf-composer-cost">{estimate}</em></span>}
      </div>
      <button type="button" className="pf-composer-go" disabled={!canSubmit} onClick={onSubmit} aria-label={action === 'compose' ? '合成视频' : '生成'}><ArrowUp size={18} /></button>
    </footer>
    {validationMessage && <p className="pf-composer-validation" role="status">{validationMessage}</p>}
  </div>
}
