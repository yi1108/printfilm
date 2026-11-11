import { X } from 'lucide-react'
import { mediaHistory, type MediaSnapshot } from './mediaHistory'

export function NodeMediaHistory({ data, writable, onRestore, onClose }: { data: Record<string, unknown>; writable: boolean; onRestore: (item: MediaSnapshot) => void; onClose: () => void }) {
  const items = [...mediaHistory(data)].reverse()
  return <div className="pf-edit-overlay"><section className="pf-media-editor" role="dialog" aria-label="节点历史记录"><header><b>节点媒体历史</b><button onClick={onClose} aria-label="关闭历史"><X size={18} /></button></header><p>替换前的媒体记录随画布保存，可恢复最近 30 个版本。</p>{!items.length && <p>此节点还没有替换记录。当前媒体保持不变。</p>}<div className="pf-node-history">{items.map((item, index) => <article key={`${item.savedAt}-${index}`}>{item.mediaType === 'video' ? <video src={item.mediaUrl} controls preload="metadata" /> : item.mediaType === 'audio' ? <audio src={item.mediaUrl} controls /> : <img src={item.mediaUrl} alt={item.label || '历史图片'} />}<div><b>{item.label || '历史媒体'}</b><small>{new Date(item.savedAt).toLocaleString()}</small><button disabled={!writable} onClick={() => onRestore(item)}>恢复到节点</button></div></article>)}</div></section></div>
}
