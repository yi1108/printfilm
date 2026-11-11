import { useState } from 'react'
import { FileText, Film, Image as ImageIcon, Mic, X } from 'lucide-react'
import type { AgentReference } from './references'

export function ReferenceThumbnail({ reference }: { reference: AgentReference }) {
  const [failed, setFailed] = useState<string[]>([])
  const { thumbnail, mediaUrl, kind, label, text } = reference
  const Icon = kind === 'video' ? Film : kind === 'audio' ? Mic : kind === 'image' ? ImageIcon : FileText
  return <span className={`pf-reference-thumbnail is-${kind}`}>
    {thumbnail && !failed.includes(thumbnail) ? <img src={thumbnail} alt={label} loading="lazy" onError={() => setFailed((urls) => [...urls, thumbnail])} />
      : kind === 'video' && mediaUrl && !failed.includes(mediaUrl) ? <video src={mediaUrl} muted playsInline preload="metadata" aria-label={`${label} 视频缩略图`} onLoadedData={(event) => { const video = event.currentTarget; if (video.currentTime === 0 && video.duration > .1) video.currentTime = .1 }} onError={() => setFailed((urls) => [...urls, mediaUrl])} />
      : kind === 'text' && text ? <span className="pf-reference-text-preview">{text}</span>
      : <Icon size={22} aria-label={label} />}
    {kind === 'video' && <Film className="pf-reference-video-badge" size={12} />}
  </span>
}

export function AgentReferences({ references, onRemove }: { references: AgentReference[]; onRemove?: (reference: AgentReference) => void }) {
  const [expanded, setExpanded] = useState(false)
  if (!references.length) return null
  return <section className={`pf-reference-strip${onRemove ? ' is-draft' : ' is-message'}`} aria-label={onRemove ? '已选参考素材' : '消息参考素材'}>
    {onRemove && <div className="pf-reference-count">已选 {references.length}<button onClick={() => references.forEach(onRemove)}>全部取消</button></div>}
    <div className="pf-reference-cards">{(onRemove && !expanded ? references.slice(0, 6) : references).map((reference) => <div className="pf-reference-card" key={reference.key} title={reference.label}>
      <ReferenceThumbnail key={`${reference.key}-${reference.thumbnail}-${reference.mediaUrl}`} reference={reference} />
      <span className="pf-reference-label">{reference.label}</span>
      {onRemove && <button type="button" className="pf-reference-remove" aria-label={`移除引用 ${reference.label}`} onClick={() => onRemove(reference)}><X size={11} /></button>}
    </div>)}{onRemove && references.length > 6 && <button className="pf-reference-expand" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '收起' : `+${references.length - 6}`}</button>}</div>
  </section>
}
