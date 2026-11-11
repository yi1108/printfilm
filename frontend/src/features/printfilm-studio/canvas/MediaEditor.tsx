import { useEffect, useRef, useState } from 'react'
import { X, Scissors, Volume2, Film, Image, Gauge } from 'lucide-react'
import { printfilmStudioApi } from '../api'
import type { MediaOperation, ProjectAsset } from '../types'
import { readProjectMedia } from './projectMedia'

const MEDIA_ACTIONS: Record<MediaOperation, string> = { trim: '截取片段', extract_audio: '提取音轨', separate: '分离音视频', mute: '移除音轨', speed: '调整速度', frame: '保存当前帧', frames: '逐帧拉片' }

export function MediaEditor({ projectId, assetId, url, kind, initial, initialStart = 0, headers, onClose, onComplete }: { projectId: number; assetId?: number; url: string; kind: 'audio' | 'video'; initial: MediaOperation; initialStart?: number; headers: HeadersInit; onClose: () => void; onComplete: (assets: ProjectAsset[]) => void }) {
  const [operation, setOperation] = useState(initial)
  const [duration, setDuration] = useState(0)
  const [start, setStart] = useState(initialStart)
  const [end, setEnd] = useState(0)
  const [speed, setSpeed] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const media = useRef<HTMLMediaElement | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => { if (media.current) media.current.playbackRate = speed }, [speed])
  const loaded = () => { const value = media.current?.duration || 0; if (Number.isFinite(value)) { setDuration(value); setEnd(value); if (media.current && initialStart > 0) media.current.currentTime = Math.min(initialStart, value) } }
  const seek = (value: number) => { setStart(value); if (media.current) media.current.currentTime = value }
  const execute = async () => {
    if (controller.current) return
    const abort = new AbortController(); controller.current = abort; setBusy(true); setError('')
    try {
      const blob = await readProjectMedia(url, projectId, assetId, abort.signal)
      if (blob.size > 100 * 1024 * 1024) throw new Error('源文件不能超过 100MB')
      const result = await printfilmStudioApi.editMedia(projectId, new File([blob], 'source.media', { type: blob.type }), { operation, start: operation === 'trim' || operation === 'frame' ? start : 0, end: operation === 'trim' ? end : undefined, speed: operation === 'speed' ? speed : 1 }, headers, abort.signal)
      if (!abort.signal.aborted) { onComplete(result.assets); onClose() }
    } catch (reason) { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '媒体处理失败') }
    finally { if (controller.current === abort) { controller.current = null; setBusy(false) } }
  }
  const choices: MediaOperation[] = kind === 'audio' ? ['trim', 'speed'] : ['trim', 'extract_audio', 'separate', 'mute', 'speed', 'frame', 'frames']
  return <div className="pf-edit-overlay"><section className="pf-media-editor" role="dialog" aria-modal="true" aria-label="媒体编辑">
    <header><b>{MEDIA_ACTIONS[operation]}</b><button onClick={() => { controller.current?.abort(); onClose() }} aria-label="关闭媒体编辑"><X size={18} /></button></header>
    <nav>{choices.map((item) => <button disabled={busy} className={operation === item ? 'is-active' : ''} key={item} onClick={() => { setOperation(item); setError('') }}>{item === 'trim' ? <Scissors size={14} /> : item === 'speed' ? <Gauge size={14} /> : item.includes('frame') ? <Image size={14} /> : item === 'extract_audio' ? <Volume2 size={14} /> : <Film size={14} />}{MEDIA_ACTIONS[item]}</button>)}</nav>
    {kind === 'video' ? <video ref={(element) => { media.current = element }} src={url} controls onLoadedMetadata={loaded} onTimeUpdate={() => { if (operation === 'trim' && media.current && media.current.currentTime >= end && !media.current.paused) { media.current.pause(); media.current.currentTime = start } }} onPlay={() => { if (operation === 'trim' && media.current && (media.current.currentTime < start || media.current.currentTime >= end)) media.current.currentTime = start }} onError={() => setError('此媒体无法播放，仍可尝试服务端处理')} /> : <audio ref={(element) => { media.current = element }} src={url} controls onLoadedMetadata={loaded} />}
    {(operation === 'trim' || operation === 'frame') && <div className="pf-media-range"><label>开始 / 定格位置 · {start.toFixed(2)} 秒<input disabled={busy} type="range" min="0" max={Math.max(0, duration - .05)} step="0.01" value={start} onChange={(event) => seek(Number(event.target.value))} /><input aria-label="开始时间" disabled={busy} type="number" min="0" max={duration} step="0.01" value={start} onChange={(event) => seek(Number(event.target.value))} /></label>{operation === 'trim' && <label>结束时间<input type="range" min={Math.min(duration, start + .01)} max={duration} step="0.01" value={end} disabled={busy} onChange={(event) => setEnd(Number(event.target.value))} /><input aria-label="结束时间" disabled={busy} type="number" min={start} max={duration} step="0.01" value={end} onChange={(event) => setEnd(Number(event.target.value))} /></label>}</div>}
    {operation === 'speed' && <label>播放速度 · {speed.toFixed(1)}×<input disabled={busy} type="range" min="0.1" max="4" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /></label>}
    <p>{operation === 'frames' ? '均匀提取 12 张关键帧，并作为独立图片节点连接到原视频。' : '处理结果保存到项目素材，并在画布创建新节点，保留原文件。'}</p>
    {error && <p role="alert" className="pf-editor-error">{error}</p>}
    <footer><span>源文件 ≤ 100MB · 时长 ≤ 10 分钟</span>{busy ? <button onClick={() => controller.current?.abort()}>取消处理</button> : <button className="is-primary" disabled={operation === 'trim' && (!duration || !(end > start) || end > duration)} onClick={() => void execute()}>应用到画布</button>}</footer>
  </section></div>
}
