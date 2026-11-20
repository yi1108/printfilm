import { useEffect, useRef, useState } from 'react'
import { AudioLines, FolderOpen, ImagePlus, Upload, Video, X } from 'lucide-react'
import { resolveToolMediaUrl, type ToolReferenceAsset, type ToolReferenceInput } from '../../api/tools'
import { checkGenerationReferenceCounts, generationReferenceFileKind, generationReferenceLimits, referenceFromAsset, roleForReferenceKind, toolReferenceAssetKind, type GenerationReference, type GenerationReferenceKind, type GenerationReferenceLimits, type VideoGenerationMode } from '../../lib/generationReferences'
import { useGenerationText } from '../../lib/generationMedia'
import ToolReferenceAssetPicker from './ToolReferenceAssetPicker'
import '../../styles/generation-references.css'

export type { GenerationReference, GenerationReferenceLimits, VideoGenerationMode } from '../../lib/generationReferences'

type Props = {
  mode: VideoGenerationMode
  limits?: GenerationReferenceLimits
  value: GenerationReference[]
  onChange: (value: GenerationReference[]) => void
  onError: (message: string) => void
  disabled?: boolean
}

const FILE_ACCEPT = { image: 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp', video: 'video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm', audio: 'audio/mpeg,audio/wav,audio/mp4,audio/aac,audio/ogg,audio/flac,.mp3,.wav,.m4a,.aac,.ogg,.flac' }

/** 展示本地或资产媒体，卸载和替换时释放本地预览地址。 */
function ReferencePreview({ reference }: { reference: GenerationReference }) {
  const [localUrl, setLocalUrl] = useState('')
  useEffect(() => {
    if (!reference.file) { setLocalUrl(''); return }
    const url = URL.createObjectURL(reference.file)
    setLocalUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [reference.file])
  const url = reference.file ? localUrl : resolveToolMediaUrl(reference.url)
  if (reference.kind === 'audio') return <div className="gen-reference-audio"><AudioLines size={25} /><audio src={url || undefined} controls preload="metadata" /></div>
  if (reference.kind === 'video') return <video src={url || undefined} muted controls preload="metadata" />
  return url ? <img src={url} alt={reference.name} /> : <ImagePlus size={24} />
}

/** 首尾帧和全能参考共用的受控资料输入，支持本地上传和全局资产选择。 */
export default function GenerationReferences({ mode, limits, value, onChange, onError, disabled = false }: Props) {
  const text = useGenerationText()
  const [targetRole, setTargetRole] = useState<ToolReferenceInput['role']>('reference_image')
  const [pickerOpen, setPickerOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const max = generationReferenceLimits(limits)
  const frameMode = mode === 'first_last_frame'
  const allowedKinds: GenerationReferenceKind[] = frameMode ? max.images > 0 ? ['image'] : [] : [
    ...(max.images > 0 ? ['image' as const] : []),
    ...(max.videos > 0 ? ['video' as const] : []),
    ...(max.audios > 0 ? ['audio' as const] : []),
  ]
  const sourceIsDisabled = disabled || allowedKinds.length === 0
  const roleName = (role: ToolReferenceInput['role']) => role === 'first_frame' ? text('首帧', 'First frame') : role === 'last_frame' ? text('尾帧', 'Last frame') : text('参考资料', 'Reference')

  // 切换模式时关闭来源选择，避免把旧模式资料加入新模式。
  useEffect(() => { setPickerOpen(false) }, [mode])

  /** 帧位替换或追加混合资料，保留已选内容并拒绝超出模型限制的新资料。 */
  function add(incoming: GenerationReference[], role?: ToolReferenceInput['role']) {
    const next = frameMode && role ? [...value.filter(item => item.role !== role), ...incoming] : [...value, ...incoming]
    const message = checkGenerationReferenceCounts(next, limits, frameMode, text)
    if (message) {
      onError(message)
      throw new Error(message)
    }
    onChange(next); onError('')
  }

  /** 校验并登记本地文件，文件在实际提交生成时统一上传。 */
  function addFiles(files: File[], role: ToolReferenceInput['role']) {
    if (!files.length || disabled) return
    if (frameMode && files.length > 1) { onError(text('每个帧位只能选择一张图片。', 'Choose one image per frame.')); return }
    const incoming: GenerationReference[] = []
    for (const file of files) {
      const kind = generationReferenceFileKind(file)
      if (!kind || !allowedKinds.includes(kind)) { onError(text(frameMode ? '首尾帧请选择图片文件。' : '当前模型不支持此类参考资料。', frameMode ? 'Choose an image for each frame.' : 'The selected model does not support this reference type.')); return }
      if (!file.size) { onError(text('参考文件不能为空。', 'Reference files cannot be empty.')); return }
      if (file.size > 40 * 1024 * 1024) { onError(text('单个参考文件不能超过 40MB。', 'Each reference file must be under 40 MB.')); return }
      incoming.push({ id: crypto.randomUUID(), role: frameMode ? role : roleForReferenceKind[kind], kind, name: file.name, url: '', file })
    }
    try { add(incoming, role) } catch { /* add 已显示对应的数量上限提示。 */ }
  }

  /** 记录目标帧位并打开系统文件选择器。 */
  function chooseLocal(role: ToolReferenceInput['role']) {
    setTargetRole(role)
    fileInput.current?.click()
  }
  /** 记录目标帧位并打开全局资产选择器。 */
  function chooseLibrary(role: ToolReferenceInput['role']) { setTargetRole(role); setPickerOpen(true) }
  /** 批量加入资产：按帧位或媒体角色自动归位，重复与不支持的类型跳过并提示。 */
  function pickAssets(assets: ToolReferenceAsset[]) {
    const incoming: GenerationReference[] = []
    let skipped = 0
    for (const asset of assets) {
      const kind = toolReferenceAssetKind(asset)
      if (!allowedKinds.includes(kind)) { skipped += 1; continue }
      // 首尾帧替换点击的帧位；全能参考按媒体类型归位
      const role = frameMode ? targetRole : roleForReferenceKind[kind]
      if (value.some(item => item.assetId === asset.id && item.role === role) || incoming.some(item => item.assetId === asset.id && item.role === role)) { skipped += 1; continue }
      incoming.push(referenceFromAsset(asset, role, text('未命名资产', 'Untitled asset')))
    }
    if (!incoming.length) {
      throw new Error(skipped ? text('这些资料已经添加或当前模型不支持，请选择其他资料。', 'These assets are already added or unsupported; choose others.') : text('当前模型不支持此类参考资料。', 'This reference type is not supported.'))
    }
    add(incoming, frameMode ? targetRole : undefined)
    if (skipped) onError(text(`已跳过 ${skipped} 份重复或不支持的资料。`, `Skipped ${skipped} duplicated or unsupported assets.`))
  }

  if (mode === 'text_to_video') return null

  return <section className={`gen-video-references${frameMode ? ' is-frames' : ' is-omni'}`} aria-label={text(frameMode ? '首尾帧参考' : '全能参考资料', frameMode ? 'Frame references' : 'Mixed references')}>
    <header><span><ImagePlus size={15} />{text(frameMode ? '画面参考' : '参考资料', frameMode ? 'Frame references' : 'References')}</span><small>{frameMode ? `${value.length}/2` : `${value.length}/${max.total}`}</small></header>
    {frameMode ? <div className="gen-frame-slots">{(['first_frame', 'last_frame'] as const).map((role, index) => {
      const reference = value.find(item => item.role === role)
      const unsupported = max.images <= index
      return <div className="gen-reference-slot" key={role} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!disabled && !unsupported) addFiles(Array.from(event.dataTransfer.files), role) }}>
        <div className="gen-reference-slot-title"><strong>{roleName(role)}</strong><small>{index === 0 ? text('必需', 'Required') : text('可选', 'Optional')}</small></div>
        {reference ? <div className="gen-reference-media"><ReferencePreview reference={reference} /><button type="button" className="gen-reference-remove" aria-label={text(`移除${roleName(role)}`, `Remove ${roleName(role)}`)} disabled={disabled} onClick={() => onChange(value.filter(item => item.id !== reference.id))}><X size={13} /></button><span title={reference.name}>{reference.name}</span></div>
          : <div className="gen-reference-placeholder"><ImagePlus size={23} /><span>{unsupported ? text('当前模型不支持', 'Not supported') : text(index === 0 ? '设定起始画面' : '设定结束画面', index === 0 ? 'Set the opening shot' : 'Set the ending shot')}</span></div>}
        <div className="gen-reference-source-actions"><button type="button" disabled={disabled || unsupported} onClick={() => chooseLocal(role)}><Upload size={13} />{text('上传', 'Upload')}</button><button type="button" disabled={disabled || unsupported} onClick={() => chooseLibrary(role)}><FolderOpen size={13} />{text('资产库', 'Library')}</button></div>
      </div>
    })}</div> : <>
      <div className="gen-mixed-reference-grid" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); addFiles(Array.from(event.dataTransfer.files), 'reference_image') }}>
        {value.map(reference => <div key={reference.id} className="gen-reference-media"><ReferencePreview reference={reference} /><button type="button" className="gen-reference-remove" aria-label={text('移除参考资料', 'Remove reference')} disabled={disabled} onClick={() => onChange(value.filter(item => item.id !== reference.id))}><X size={13} /></button><span title={reference.name}>{reference.name}</span><small className="gen-reference-kind">{reference.kind === 'image' ? <ImagePlus size={12} /> : reference.kind === 'video' ? <Video size={12} /> : <AudioLines size={12} />}</small></div>)}
        {value.length === 0 && <div className="gen-reference-placeholder"><ImagePlus size={26} /><span>{text('图片、视频、音频', 'Images, video and audio')}</span><small>{text('拖放文件到这里', 'Drop files here')}</small></div>}
      </div>
      <div className="gen-reference-source-actions gen-mixed-reference-actions"><button type="button" disabled={sourceIsDisabled || value.length >= max.total} onClick={() => chooseLocal('reference_image')}><Upload size={14} />{text('上传资料', 'Upload')}</button><button type="button" disabled={sourceIsDisabled || value.length >= max.total} onClick={() => chooseLibrary('reference_image')}><FolderOpen size={14} />{text('从资产库选择', 'Asset library')}</button></div>
    </>}
    <p className="gen-reference-limits">{frameMode ? text('上传首帧，可选尾帧，让镜头连接起止画面。', 'Set a first frame and an optional last frame.') : text(`图片 ${max.images} 张 · 视频 ${max.videos} 段 · 音频 ${max.audios} 段`, `${max.images} images · ${max.videos} videos · ${max.audios} audio clips`)}</p>
    <input ref={fileInput} type="file" hidden multiple={!frameMode} accept={allowedKinds.map(kind => FILE_ACCEPT[kind]).join(',')} onChange={event => { addFiles(Array.from(event.target.files || []), targetRole); event.target.value = '' }} />
    <ToolReferenceAssetPicker open={pickerOpen} onClose={() => setPickerOpen(false)} allowedKinds={allowedKinds} multiple={!frameMode} onPick={pickAssets} />
  </section>
}
