import { useEffect, useRef, useState } from 'react'
import { Box, Camera, Film, Pause, Play, Plus, Save, Trash2, X } from 'lucide-react'
import { normalizeScene, renderScene, sceneAtTime, type DirectorScene, type SceneObject } from './scene3d'
import { canvasBlob } from './maskMedia'

export function DirectorEditor({ initial, writable, onSave, onExport, onClose }: { initial: unknown; writable: boolean; onSave: (scene: DirectorScene) => void; onExport: (scene: DirectorScene, blob: Blob, kind: 'image' | 'video') => Promise<void>; onClose: () => void }) {
  const [scene, setScene] = useState(() => normalizeScene(initial))
  const [selected, setSelected] = useState<string | null>(scene.objects[0]?.id || null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [previewFrame, setPreviewFrame] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canvas = useRef<HTMLCanvasElement>(null)
  const drag = useRef<{ x: number; y: number; yaw: number; pitch: number } | null>(null)
  const alive = useRef(true)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const selectedObject = scene.objects.find((o) => o.id === selected)
  useEffect(() => { alive.current = true; return () => { alive.current = false; if (recorderRef.current?.state === 'recording') recorderRef.current.stop() } }, [])
  useEffect(() => { if (canvas.current && !busy) renderScene(canvas.current, previewFrame ? sceneAtTime(scene, time) : scene) }, [scene, time, previewFrame, busy])
  useEffect(() => {
    if (!playing || busy) return
    const start = performance.now() - time * 1000
    let frame = 0
    const tick = () => { const next = (performance.now() - start) / 1000; setTime(Math.min(next, scene.duration)); if (next >= scene.duration) { setPlaying(false); return }; frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
    // The playback clock captures the scrub position only when playback starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, busy, scene.duration])
  const changeObject = (key: keyof SceneObject, value: string | number) => { setPreviewFrame(false); setScene((current) => ({ ...current, objects: current.objects.map((o) => o.id === selected ? { ...o, [key]: value } : o) })) }
  const add = (kind: 'person' | 'box') => { const id = crypto.randomUUID(); setScene((current) => ({ ...current, objects: [...current.objects, { id, name: kind === 'person' ? `角色 ${current.objects.length + 1}` : '道具', kind, x: current.objects.length * .7, y: 0, z: 0, rotation: 0, scale: 1, pose: 0, color: kind === 'person' ? '#b7a0ce' : '#a0b8ce' }] })); setSelected(id); setPreviewFrame(false) }
  const recordFrame = () => { const displayed = previewFrame ? sceneAtTime(scene, time) : scene; const frame = { time: Math.round(time * 10) / 10, camera: structuredClone(displayed.camera), objects: structuredClone(displayed.objects) }; setScene((current) => ({ ...current, frames: [...current.frames.filter((f) => f.time !== frame.time), frame].sort((a, b) => a.time - b.time) })) }
  const exportMedia = async (kind: 'image' | 'video') => {
    if (!canvas.current || busy || !writable) return
    setBusy(true); setPlaying(false); setError('')
    try {
      const el = canvas.current
      if (kind === 'image') { renderScene(el, previewFrame ? sceneAtTime(scene, time) : scene); await onExport(scene, await canvasBlob(el), 'image'); return }
      if (scene.frames.length < 2) throw new Error('请在两个不同时间点记录关键帧后导出视频')
      if (typeof MediaRecorder === 'undefined' || !el.captureStream) throw new Error('当前浏览器不支持视频导出，请使用最新版 Chrome 或 Edge')
      const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find((mime) => MediaRecorder.isTypeSupported(mime))
      if (!mimeType) throw new Error('浏览器不支持 WebM 编码')
      const stream = el.captureStream(24)
      try {
        const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_000_000 }); recorderRef.current = recorder
        const chunks: Blob[] = []
        let hidden = false, frame = 0
        const visibility = () => { if (document.hidden && recorder.state === 'recording') { hidden = true; recorder.stop() } }
        document.addEventListener('visibilitychange', visibility)
        try {
          const blob = await new Promise<Blob>((resolve, reject) => {
            recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
            recorder.onerror = () => reject(new Error('视频编码失败'))
            recorder.onstop = () => hidden ? reject(new Error('导出期间请保持页面可见，已取消本次导出')) : resolve(new Blob(chunks, { type: 'video/webm' }))
            renderScene(el, sceneAtTime(scene, 0)); recorder.start(250)
            const start = performance.now()
            const tick = () => {
              if (recorder.state !== 'recording') return
              const next = Math.min((performance.now() - start) / 1000, scene.duration)
              renderScene(el, sceneAtTime(scene, next)); setTime(next)
              if (next >= scene.duration || !alive.current) { recorder.stop(); return }
              frame = requestAnimationFrame(tick)
            }
            frame = requestAnimationFrame(tick)
          })
          if (alive.current) await onExport(scene, blob, 'video')
        } finally { cancelAnimationFrame(frame); document.removeEventListener('visibilitychange', visibility); if (recorder.state === 'recording') recorder.stop() }
      } finally { stream.getTracks().forEach((track) => track.stop()); recorderRef.current = null }
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : '导出失败') }
    finally { if (alive.current) setBusy(false) }
  }
  return <div className="pf-workflow-backdrop"><section className="pf-workflow-dialog pf-director-dialog" role="dialog" aria-modal="true" aria-label="3D 导演台"><header><h2><Box size={20} />3D 导演台</h2><button disabled={busy} onClick={onClose} aria-label="关闭导演台"><X size={20} /></button></header><p>拖动预览调整机位，摆放角色和道具。在时间轴记录不同机位与姿态，预演镜头并导出到画布。</p>
    <div className="pf-director-layout"><div><canvas ref={canvas} width={1280} height={720} onPointerDown={(e) => { if (!writable || busy) return; e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, yaw: scene.camera.yaw, pitch: scene.camera.pitch }; setPreviewFrame(false) }} onPointerMove={(e) => { if (!drag.current) return; const d = drag.current; setScene((current) => ({ ...current, camera: { ...current.camera, yaw: d.yaw + (e.clientX - d.x) * .3, pitch: Math.max(-10, Math.min(80, d.pitch + (e.clientY - d.y) * .2)) } })) }} onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }} />
      <div className="pf-director-timeline"><button disabled={busy || !scene.frames.length} onClick={() => { if (time >= scene.duration) setTime(0); setPreviewFrame(true); setPlaying((value) => !value) }}>{playing ? <Pause size={16} /> : <Play size={16} />}</button><input aria-label="时间轴" type="range" min="0" max={scene.duration} step=".05" value={time} disabled={busy} onChange={(e) => { setTime(Number(e.target.value)); setPreviewFrame(true); setPlaying(false) }} /><span>{time.toFixed(1)}s / {scene.duration}s</span><button disabled={!writable || busy} onClick={recordFrame}><Plus size={16} />记录关键帧</button></div>
      <div className="pf-keyframes">{scene.frames.map((frame, index) => <span key={index}><button disabled={busy} onClick={() => { setTime(frame.time); setScene((current) => ({ ...current, camera: structuredClone(frame.camera), objects: structuredClone(frame.objects) })); setPreviewFrame(false); setPlaying(false) }}>{frame.time.toFixed(1)}s · 机位 {index + 1}</button><button aria-label={`删除关键帧 ${index + 1}`} disabled={!writable || busy} onClick={() => setScene((current) => ({ ...current, frames: current.frames.filter((_, i) => i !== index) }))}><X size={12} /></button></span>)}</div></div>
    <fieldset disabled={!writable || busy}><legend>场景与机位</legend><div className="pf-mask-tools"><button disabled={scene.objects.length >= 30} onClick={() => add('person')}><Plus size={15} />角色</button><button disabled={scene.objects.length >= 30} onClick={() => add('box')}><Plus size={15} />道具</button></div><select aria-label="场景物体" value={selected || ''} onChange={(e) => setSelected(e.target.value)}>{scene.objects.map((object) => <option key={object.id} value={object.id}>{object.name}</option>)}</select>
      {selectedObject && <><input aria-label="物体名称" value={selectedObject.name} onChange={(e) => changeObject('name', e.target.value)} />{(['x', 'y', 'z', 'rotation', 'scale', 'pose'] as const).map((key) => <label key={key}>{({ x: '左右', y: '高度', z: '前后', rotation: '朝向', scale: '大小', pose: '动作' })[key]}<input type="range" min={key === 'scale' ? .2 : key === 'y' ? 0 : key === 'rotation' ? -180 : key === 'pose' ? -80 : -10} max={key === 'scale' ? 4 : key === 'rotation' ? 180 : key === 'pose' ? 80 : 10} step={key === 'pose' || key === 'rotation' ? 1 : .1} value={selectedObject[key]} onChange={(e) => changeObject(key, Number(e.target.value))} /><output>{selectedObject[key]}</output></label>)}<label>颜色<input type="color" value={selectedObject.color} onChange={(e) => changeObject('color', e.target.value)} /></label><button onClick={() => { setScene((current) => ({ ...current, objects: current.objects.filter((o) => o.id !== selected) })); setSelected(null) }}><Trash2 size={14} />删除物体</button></>}
      <hr />{(['distance', 'fov', 'targetY'] as const).map((key) => <label key={key}>{({ distance: '机位距离', fov: '视角', targetY: '取景高度' })[key]}<input type="range" min={key === 'fov' ? 15 : key === 'distance' ? 1.5 : -2} max={key === 'fov' ? 100 : key === 'distance' ? 25 : 5} step=".1" value={scene.camera[key]} onChange={(e) => { setPreviewFrame(false); setScene((current) => ({ ...current, camera: { ...current.camera, [key]: Number(e.target.value) } })) }} /></label>)}<label>时长<input type="number" min="1" max="30" value={scene.duration} onChange={(e) => { const duration = Math.max(1, Math.min(30, Number(e.target.value))); setTime((t) => Math.min(t, duration)); setScene((current) => ({ ...current, duration, frames: current.frames.filter((f) => f.time <= duration) })) }} /></label><label>背景<input type="color" value={scene.background} onChange={(e) => setScene((current) => ({ ...current, background: e.target.value }))} /></label></fieldset></div>
    {error && <p role="alert" className="pf-workflow-error">{error}</p>}<footer><button disabled={!writable || busy} onClick={() => { onSave(scene); onClose() }}><Save size={16} />保存场景</button><button disabled={!writable || busy} onClick={() => void exportMedia('image')}><Camera size={16} />导出当前帧</button><button disabled={!writable || busy} onClick={() => void exportMedia('video')}><Film size={16} />{busy ? '正在导出…' : '导出运镜视频'}</button></footer>
  </section></div>
}
