import { useRef, useState } from 'react'
import { Camera, Maximize, Pause, Play, Volume2, VolumeX } from 'lucide-react'

const time = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`
export function InlineVideoPlayer({ url, title, writable, onSize, onCapture }: {
  url: string; title: string; writable: boolean; onSize: (width: number, height: number) => void; onCapture: (time: number) => void
}) {
  const video = useRef<HTMLVideoElement | null>(null)
  const [duration, setDuration] = useState(0)
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [captureMenu, setCaptureMenu] = useState(false)
  const [error, setError] = useState('')
  return <div className="pf-inline-player">
    <video ref={video} src={url} aria-label={title} playsInline preload="metadata" draggable={false} onLoadedMetadata={(event) => { const element = event.currentTarget; setDuration(Number.isFinite(element.duration) ? element.duration : 0); onSize(element.videoWidth, element.videoHeight) }} onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => setError('媒体暂时无法播放')} onDoubleClick={(event) => event.stopPropagation()} />
    {error && <span role="status" className="pf-inline-error">{error}</span>}
    <div className="pf-inline-controls nodrag nopan nowheel" onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
      <button aria-label={playing ? '暂停视频' : '播放视频'} disabled={!duration} onClick={() => { if (!video.current) return; if (video.current.paused) void video.current.play().catch(() => setError('无法播放此格式')); else video.current.pause() }}>{playing ? <Pause size={14} /> : <Play size={14} />}</button>
      <span>{time(position)}</span><input aria-label="视频播放进度" type="range" min="0" max={duration || 1} step="0.01" value={position} disabled={!duration} onChange={(event) => { if (video.current) video.current.currentTime = Number(event.target.value) }} /><span>/{time(duration)}</span>
      <button aria-label={muted ? '取消静音' : '静音'} onClick={() => { if (video.current) { video.current.muted = !muted; setMuted(!muted) } }}>{muted ? <VolumeX size={14} /> : <Volume2 size={14} />}</button>
      {writable && <div className="pf-inline-capture"><button aria-label="截取视频帧" aria-expanded={captureMenu} disabled={!duration} onClick={() => setCaptureMenu(!captureMenu)}><Camera size={14} /></button>{captureMenu && <div role="menu">{[['当前帧', position], ['首帧', 0], ['尾帧', Math.max(0, duration - .05)]].map(([label, at]) => <button role="menuitem" key={label} onClick={() => { onCapture(Number(at)); setCaptureMenu(false) }}>截取{label}</button>)}</div>}</div>}
      <button aria-label="全屏视频" onClick={() => { const element = video.current; if (!element) return; element.controls = true; void element.requestFullscreen().catch(() => { element.controls = false; setError('当前浏览器不支持视频全屏') }); element.onfullscreenchange = () => { element.controls = window.document.fullscreenElement === element } }}><Maximize size={14} /></button>
    </div>
  </div>
}
