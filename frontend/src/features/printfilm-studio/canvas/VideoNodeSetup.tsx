import { useState } from 'react'
import { ImagePlus, Plus, X } from 'lucide-react'

export function VideoNodeSetup({ mode, items, initialIds, onApply, onCreate, onLibrary, onClose }: {
  mode: 'image_to_video' | 'first_last_frame'; items: { id: string; label: string; url: string }[]; initialIds: string[]
  onApply: (ids: string[]) => void; onCreate: () => void; onLibrary: () => void; onClose: () => void
}) {
  const limit = mode === 'first_last_frame' ? 2 : 1
  const [ids, setIds] = useState(() => Array.from({ length: limit }, (_, index) =>
    items.some((item) => item.id === initialIds[index]) ? initialIds[index] : '',
  ))
  const [slot, setSlot] = useState(ids[0] && limit === 2 ? 1 : 0)
  const choose = (id: string) => {
    const next = ids.map((current, index) => index === slot ? id : current === id ? '' : current)
    setIds(next)
    const empty = next.indexOf('')
    if (empty >= 0) setSlot(empty)
  }
  return <div className="pf-edit-overlay"><section className="pf-video-setup" role="dialog" aria-label="选择视频参考图片" aria-modal="true">
    <header><div><b>{limit === 2 ? '选择首帧与尾帧' : '选择参考图片'}</b><p>{limit === 2 ? '先选槽位，再选图片。输出比例跟随首帧。' : '从画布选择已有图片，或创建新的图片节点。'}</p></div><button aria-label="关闭参考选择" onClick={onClose}><X size={18} /></button></header>
    {limit === 2 && <div className="pf-video-frame-slots">{['首帧', '尾帧'].map((label, index) => <button type="button" key={label} aria-pressed={slot === index} onClick={() => setSlot(index)}>{label} · {items.find(item => item.id === ids[index])?.label || '待选择'}</button>)}</div>}
    <div className="pf-video-setup-grid">{items.map((item) => <button key={item.id} aria-pressed={ids.includes(item.id)} onClick={() => choose(item.id)}><img src={item.url} alt="" loading="lazy" /><span>{item.label}</span>{ids.includes(item.id) && <b>{limit === 1 ? '参考图' : ids.indexOf(item.id) === 0 ? '首帧' : '尾帧'}</b>}</button>)}</div>
    {!items.length && <p>画布上暂无图片，可从素材库选择或新建图片节点。</p>}
    <footer><button onClick={onCreate}><Plus size={16} />新建图片节点</button><button onClick={onLibrary}><ImagePlus size={16} />素材库</button><button className="is-primary" disabled={ids.some(id => !id) || new Set(ids).size !== limit} onClick={() => onApply(ids)}>完成 / 返回视频节点</button></footer>
  </section></div>
}
