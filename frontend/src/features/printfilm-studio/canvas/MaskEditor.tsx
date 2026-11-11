import { useEffect, useRef, useState } from 'react'
import { Brush, Eraser, Undo2, X } from 'lucide-react'
import { canvasBlob, readCanvasImage } from './maskMedia'
import { useReadableMedia } from './projectMedia'
import { ImageCropEditor } from './ImageCropEditor'
import './imageEditor.css'

export function MaskEditor({ url, projectId, assetId, initialMode = 'edit', onSave, onCrop, onClose }: { url: string; projectId?: number; assetId?: number; initialMode?: 'edit' | 'crop'; onSave: (mask: Blob, guide: Blob, prompt: string) => Promise<void>; onCrop: (blob: Blob) => Promise<void>; onClose: () => void }) {
  const readable = useReadableMedia(url, projectId, assetId)
  const canvas = useRef<HTMLCanvasElement>(null)
  const original = useRef<HTMLImageElement | null>(null)
  const strokes = useRef<ImageData[]>([])
  const last = useRef<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState(36)
  const [erase, setErase] = useState(false)
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [mode, setMode] = useState(initialMode)
  const [prompt, setPrompt] = useState('')
  useEffect(() => { if (!readable.url) return; let active = true; void readCanvasImage(readable.url).then((image) => { if (!active || !canvas.current) return; original.current = image; canvas.current.width = image.naturalWidth; canvas.current.height = image.naturalHeight; setReady(true) }).catch((e) => { if (active) setError(e.message) }); return () => { active = false } }, [readable.url])
  useEffect(() => { if (readable.error) setError(readable.error) }, [readable.error])
  const draw = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!last.current || !ready || busy) return
    const el = event.currentTarget, bounds = el.getBoundingClientRect(), ctx = el.getContext('2d')!
    const point = { x: (event.clientX - bounds.left) * el.width / bounds.width, y: (event.clientY - bounds.top) * el.height / bounds.height }
    ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over'
    ctx.strokeStyle = '#ef4444'; ctx.lineWidth = size * el.width / bounds.width; ctx.lineCap = 'round'; ctx.lineJoin = 'round'
    ctx.beginPath(); ctx.moveTo(last.current.x, last.current.y); ctx.lineTo(point.x, point.y); ctx.stroke(); last.current = point
  }
  const save = async () => {
    if (!canvas.current || !original.current || busy) return
    setError(''); setBusy(true)
    try {
      const el = canvas.current, ctx = el.getContext('2d')!
      if (!prompt.trim()) throw new Error('请描述选区内希望出现的内容')
      if (!ctx.getImageData(0, 0, el.width, el.height).data.some((value, index) => index % 4 === 3 && value > 0)) throw new Error('请先涂抹需要重绘的区域')
      const guide = document.createElement('canvas'); guide.width = el.width; guide.height = el.height
      const g = guide.getContext('2d')!; g.drawImage(original.current, 0, 0); g.globalAlpha = .55; g.drawImage(el, 0, 0)
      await onSave(await canvasBlob(el), await canvasBlob(guide), prompt.trim())
    } catch (e) { setError(e instanceof Error ? e.message : '蒙版保存失败') }
    finally { setBusy(false) }
  }
  return <div className="pf-edit-overlay"><section className="pf-image-edit-dialog" role="dialog" aria-modal="true" aria-label="编辑图片"><header><h2>编辑图片</h2><button disabled={busy} onClick={onClose} aria-label="关闭图片编辑"><X size={20} /></button></header><div className="pf-image-edit-tabs"><button disabled={busy} aria-pressed={mode === 'edit'} onClick={() => setMode('edit')}>局部编辑</button><button disabled={busy} aria-pressed={mode === 'crop'} onClick={() => setMode('crop')}>裁剪</button></div>
    {mode === 'crop' && readable.url && <ImageCropEditor url={readable.url} onSave={onCrop} onBusy={setBusy} />}
    <div hidden={mode !== 'edit'}>
    <div className="pf-mask-tools"><button className={!erase ? 'is-active' : ''} onClick={() => setErase(false)}><Brush size={16} />画笔</button><button className={erase ? 'is-active' : ''} onClick={() => setErase(true)}><Eraser size={16} />橡皮</button><label>笔刷 <input type="range" min="4" max="120" value={size} onChange={(e) => setSize(Number(e.target.value))} /> {size}</label><button disabled={busy} onClick={() => { const previous = strokes.current.pop(); if (previous) canvas.current?.getContext('2d')?.putImageData(previous, 0, 0) }}><Undo2 size={16} />撤销</button><button disabled={busy || !ready} onClick={() => { const el = canvas.current!; const ctx = el.getContext('2d')!; strokes.current = [...strokes.current.slice(-9), ctx.getImageData(0, 0, el.width, el.height)]; ctx.globalCompositeOperation = 'source-over'; ctx.fillStyle = '#ef4444'; ctx.fillRect(0, 0, el.width, el.height) }}>全选</button><button disabled={busy} onClick={() => canvas.current?.getContext('2d')?.clearRect(0, 0, canvas.current.width, canvas.current.height)}>清除选区</button></div>
    <div className="pf-image-edit-stage"><div className="pf-image-edit-surface" style={{ aspectRatio: original.current ? `${original.current.naturalWidth}/${original.current.naturalHeight}` : '16/9', width: `min(100%, ${original.current ? Math.min(900, 560 * original.current.naturalWidth / original.current.naturalHeight) : 720}px)` }}><img src={readable.url || url} alt="原图" draggable={false} /><canvas ref={canvas} onPointerDown={(e) => { if (!ready || busy) return; e.currentTarget.setPointerCapture(e.pointerId); const el = e.currentTarget, bounds = el.getBoundingClientRect(); strokes.current = [...strokes.current.slice(-9), el.getContext('2d')!.getImageData(0, 0, el.width, el.height)]; last.current = { x: (e.clientX - bounds.left) * el.width / bounds.width + .01, y: (e.clientY - bounds.top) * el.height / bounds.height }; draw(e) }} onPointerMove={draw} onPointerUp={() => { last.current = null }} onPointerCancel={() => { last.current = null }} /></div></div>
    <label className="pf-image-edit-prompt">修改内容<textarea disabled={busy} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="描述选区内希望出现的内容" /></label>
    <footer><span>保留原图，修改结果保存为新节点</span><button className="is-primary" onClick={() => void save()} disabled={!ready || busy || !prompt.trim()}>{busy ? '正在保存选区…' : '生成修改图'}</button></footer></div>{error && <p className="pf-workflow-error" role="alert">{error}</p>}</section></div>
}
