import { useEffect, useRef, useState } from 'react'
import { Brush, Camera, RotateCcw, Sun, X } from 'lucide-react'
import { imageToolPrompt, panoramaUv, type ImageToolMode, type ImageToolSettings } from './imageToolParameters'
import './imageTools.css'
import { useReadableMedia } from './projectMedia'

type Stroke = { color: string; width: number; points: [number, number][] }
const initialSettings: ImageToolSettings = { yaw: 0, pitch: 20, brightness: 65, color: '#fff3dd', distance: 4.8, lens: 50, panorama: 'sphere' }
export function ImageToolsEditor({ url, mode, writable, projectId, assetId, onClose, onPrompt, onExport }: { url: string; mode: ImageToolMode; writable: boolean; projectId?: number; assetId?: number; onClose: () => void; onPrompt: (prompt: string) => void; onExport: (blob: Blob, label: string) => Promise<void> }) {
  const readable = useReadableMedia(url, projectId, assetId)
  const [settings, setSettings] = useState(initialSettings), [strokes, setStrokes] = useState<Stroke[]>([]), [ink, setInk] = useState('#ef4444'), [penSize, setPenSize] = useState(6)
  const [fov, setFov] = useState(70), [error, setError] = useState(''), [busy, setBusy] = useState(false), [loaded, setLoaded] = useState(false)
  const canvas = useRef<HTMLCanvasElement>(null), source = useRef<HTMLImageElement | null>(null), pixels = useRef<ImageData | null>(null), drawing = useRef<Stroke | null>(null), dragging = useRef<{ x: number; y: number; yaw: number; pitch: number } | null>(null)
  const title = { mark: '图片标注', lighting: '灯光编辑', angle: '多角度', panorama: '全景取景' }[mode]
  useEffect(() => {
    if (!readable.url) return
    let alive = true
    const img = new Image(); img.crossOrigin = 'anonymous'
    img.onload = () => {
      if (!alive) return
      source.current = img
      try { const texture = document.createElement('canvas'); const ratio = Math.min(1, 2048 / img.naturalWidth); texture.width = Math.round(img.naturalWidth * ratio); texture.height = Math.round(img.naturalHeight * ratio); const context = texture.getContext('2d')!; context.drawImage(img, 0, 0, texture.width, texture.height); pixels.current = context.getImageData(0, 0, texture.width, texture.height); setLoaded(true) } catch { setError('图片无法读取，请检查素材跨域权限') }
    }
    img.onerror = () => { if (alive) setError('图片加载失败') }; img.src = readable.url
    return () => { alive = false }
  }, [readable.url])
  useEffect(() => { if (readable.error) setError(readable.error) }, [readable.error])
  useEffect(() => {
    const el = canvas.current, img = source.current
    if (!el || !img || !loaded) return
    const ctx = el.getContext('2d')!
    if (mode === 'panorama' && pixels.current) {
      el.width = 800; el.height = 450
      const target = ctx.createImageData(el.width, el.height), texture = pixels.current
      for (let y = 0; y < el.height; y++) for (let x = 0; x < el.width; x++) {
        const [u, v] = panoramaUv((x + .5) / el.width * 2 - 1, (y + .5) / el.height * 2 - 1, el.width / el.height, settings.yaw, settings.pitch, fov, settings.panorama === 'cylinder')
        const a = (Math.min(texture.height - 1, Math.floor(v * texture.height)) * texture.width + Math.floor(u * texture.width)) * 4, b = (y * el.width + x) * 4
        target.data[b] = texture.data[a]; target.data[b + 1] = texture.data[a + 1]; target.data[b + 2] = texture.data[a + 2]; target.data[b + 3] = 255
      }
      ctx.putImageData(target, 0, 0); return
    }
    const ratio = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight)); el.width = Math.round(img.naturalWidth * ratio); el.height = Math.round(img.naturalHeight * ratio)
    ctx.drawImage(img, 0, 0, el.width, el.height)
    for (const stroke of strokes) { ctx.beginPath(); ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = stroke.color; ctx.lineWidth = stroke.width; stroke.points.forEach(([x, y], i) => i ? ctx.lineTo(x * el.width, y * el.height) : ctx.moveTo(x * el.width, y * el.height)); ctx.stroke() }
  }, [loaded, mode, settings, strokes, fov])
  const update = (key: keyof ImageToolSettings, value: number | string) => setSettings((current) => ({ ...current, [key]: value }))
  const exportImage = async () => {
    if (!canvas.current || busy) return
    setBusy(true); setError('')
    try { const blob = await new Promise<Blob>((resolve, reject) => canvas.current!.toBlob((value) => value ? resolve(value) : reject(new Error('无法导出图片')), 'image/png')); await onExport(blob, mode === 'mark' ? '标注图片' : `全景取景_${settings.yaw}°`); onClose() } catch (reason) { setError(reason instanceof Error ? reason.message : '导出失败') } finally { setBusy(false) }
  }
  return <div className="pf-edit-overlay"><section className="pf-image-tools-editor" role="dialog" aria-modal="true" aria-label={title}><header><b>{mode === 'lighting' ? <Sun size={18} /> : mode === 'mark' ? <Brush size={18} /> : <Camera size={18} />}{title}</b><button disabled={busy} aria-label={`关闭${title}`} onClick={onClose}><X size={18} /></button></header><div className="pf-image-tools-layout"><div className="pf-image-tools-preview"><canvas ref={canvas} aria-label={mode === 'mark' ? '标注画布' : '图片工具预览'} onPointerDown={(event) => { if (!writable || busy) return; const el = event.currentTarget; el.setPointerCapture(event.pointerId); const bounds = el.getBoundingClientRect(); if (mode === 'mark') { drawing.current = { color: ink, width: penSize, points: [[(event.clientX - bounds.left) / bounds.width, (event.clientY - bounds.top) / bounds.height]] }; setStrokes((current) => [...current, drawing.current!]) } else if (mode === 'panorama') dragging.current = { x: event.clientX, y: event.clientY, yaw: settings.yaw, pitch: settings.pitch } }} onPointerMove={(event) => { if (drawing.current) { const bounds = event.currentTarget.getBoundingClientRect(); drawing.current.points.push([(event.clientX - bounds.left) / bounds.width, (event.clientY - bounds.top) / bounds.height]); setStrokes((current) => [...current]) } else if (dragging.current) { const start = dragging.current; setSettings((current) => ({ ...current, yaw: Math.round(((start.yaw + (start.x - event.clientX) * .3 + 540) % 360) - 180), pitch: Math.round(Math.max(-80, Math.min(80, start.pitch + (event.clientY - start.y) * .25))) })) } }} onPointerUp={() => { drawing.current = null; dragging.current = null }} onPointerCancel={() => { drawing.current = null; dragging.current = null }} /></div><aside><fieldset disabled={busy || !writable}>
      {mode === 'mark' ? <><label>标注颜色<input aria-label="标注颜色" type="color" value={ink} onChange={(event) => setInk(event.target.value)} /></label><label>画笔粗细<input aria-label="画笔粗细" type="range" min={2} max={24} value={penSize} onChange={(event) => setPenSize(Number(event.target.value))} /></label><button disabled={!strokes.length} onClick={() => setStrokes((current) => current.slice(0, -1))}><RotateCcw size={14} />撤销一笔</button><button disabled={!strokes.length} onClick={() => setStrokes([])}>清空标注</button></> : <><label>水平角 · {settings.yaw}°<input aria-label="水平角" type="range" min={-180} max={180} value={settings.yaw} onChange={(event) => update('yaw', Number(event.target.value))} /></label><label>俯仰角 · {settings.pitch}°<input aria-label="俯仰角" type="range" min={-80} max={80} value={settings.pitch} onChange={(event) => update('pitch', Number(event.target.value))} /></label>{mode !== 'panorama' && <div className="pf-image-angle-map" aria-label="方向示意"><span>主体</span><i style={{ transform: `rotate(${settings.yaw}deg) translateY(-52px) rotate(${-settings.yaw}deg)`, background: mode === 'lighting' ? settings.color : '#7397c4' }}>{mode === 'lighting' ? '光' : '机'}</i></div>}{mode === 'lighting' && <><label>亮度 · {settings.brightness}%<input aria-label="光照亮度" type="range" min={0} max={100} value={settings.brightness} onChange={(event) => update('brightness', Number(event.target.value))} /></label><label>光线颜色<input aria-label="光线颜色" type="color" value={settings.color} onChange={(event) => update('color', event.target.value)} /></label><div className="pf-image-presets">{[['柔光', 0, 25, '#fff3dd'], ['侧光', -45, 35, '#ffffff'], ['背光', 180, 20, '#72a7ff'], ['夕阳', -120, 10, '#ffad69']].map(([name, yaw, pitch, color]) => <button key={name} onClick={() => setSettings((current) => ({ ...current, yaw: Number(yaw), pitch: Number(pitch), color: String(color) }))}>{name}</button>)}</div></>}{mode === 'angle' && <><label>相机距离 · {settings.distance} 米<input aria-label="相机距离" type="range" min={2} max={10} step={.1} value={settings.distance} onChange={(event) => update('distance', Number(event.target.value))} /></label><label>镜头<select aria-label="镜头焦距" value={settings.lens} onChange={(event) => update('lens', Number(event.target.value))}><option value={50}>50mm 标准</option><option value={24}>24mm 广角</option></select></label><div className="pf-image-presets">{[['正面', 0], ['左侧', -90], ['右侧', 90], ['背面', 180]].map(([name, yaw]) => <button key={name} onClick={() => update('yaw', Number(yaw))}>{name}</button>)}</div></>}{mode === 'panorama' && <><label>全景类型<select aria-label="全景类型" value={settings.panorama} onChange={(event) => update('panorama', event.target.value)}><option value="sphere">球面 · 720°</option><option value="cylinder">柱面 · 360°</option></select></label><label>取景视角 · {fov}°<input aria-label="取景视角" type="range" min={30} max={110} value={fov} onChange={(event) => setFov(Number(event.target.value))} /></label><p>拖动画面调整视角。球面材质建议 2:1，柱面材质建议 4:1。</p><button onClick={() => onPrompt(imageToolPrompt('panorama', settings))}>用此图生成全景材质</button></>}</>}
    </fieldset><p>{mode === 'lighting' || mode === 'angle' ? '方向示意用于设置生成要求，实际效果由所选图片模型生成。' : '导出为新图片节点，保留原始素材。'}</p></aside></div>{error && <p role="alert" className="pf-editor-error">{error}</p>}<footer><span>{busy ? '正在保存…' : loaded ? '图片已就绪' : '正在读取图片…'}</span><button className="is-primary" disabled={busy || !loaded || !writable} onClick={() => { if (mode === 'mark' || mode === 'panorama') void exportImage(); else onPrompt(imageToolPrompt(mode, settings)) }}>{mode === 'mark' ? '保存标注到画布' : mode === 'panorama' ? '保存当前取景' : '使用此设置生成图片'}</button></footer></section></div>
}
