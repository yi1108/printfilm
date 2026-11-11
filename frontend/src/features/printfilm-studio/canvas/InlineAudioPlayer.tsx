import { useEffect, useRef, useState } from 'react'
import { Pause, Play, Volume2, VolumeX } from 'lucide-react'
import './inlineAudio.css'
import { readProjectMedia } from './projectMedia'

const timeLabel = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
export function InlineAudioPlayer({ url, title, projectId, assetId }: { url: string; title: string; projectId?: number; assetId?: number }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [duration, setDuration] = useState(0), [position, setPosition] = useState(0), [playing, setPlaying] = useState(false)
  const [volume, setVolume] = useState(1), [speed, setSpeed] = useState(1), [peaks, setPeaks] = useState<number[]>([]), [error, setError] = useState('')
  useEffect(() => {
    const abort = new AbortController(); let context: AudioContext | undefined
    void (async () => {
      try {
        const blob = await readProjectMedia(url, projectId, assetId, abort.signal)
        if (blob.size > 30 * 1024 * 1024) return
        const bytes = await blob.arrayBuffer()
        if (abort.signal.aborted || bytes.byteLength > 30 * 1024 * 1024) return
        context = new AudioContext()
        const buffer = await context.decodeAudioData(bytes)
        const channel = buffer.getChannelData(0), width = 80, stride = Math.ceil(channel.length / width)
        const values = Array.from({ length: width }, (_, index) => {
          let peak = 0
          for (let sample = index * stride; sample < Math.min((index + 1) * stride, channel.length); sample += Math.max(1, Math.floor(stride / 150))) peak = Math.max(peak, Math.abs(channel[sample]))
          return peak
        })
        const max = Math.max(...values, .01)
        if (!abort.signal.aborted) setPeaks(values.map((value) => value / max))
      } catch { /* Playback still works when waveform decoding is unavailable. */ }
      finally { if (context && context.state !== 'closed') void context.close() }
    })()
    return () => { abort.abort(); if (context && context.state !== 'closed') void context.close().catch(() => undefined) }
  }, [url, projectId, assetId])
  const seek = (value: number) => { if (audio.current) { audio.current.currentTime = value; setPosition(value) } }
  return <div className="pf-audio-player nodrag nopan nowheel" onPointerDown={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
    <audio ref={audio} src={url} aria-label={title} preload="metadata" onLoadedMetadata={(event) => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)} onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => setError('此音频暂时无法播放')} />
    <div className="pf-audio-wave" onClick={(event) => { const bounds = event.currentTarget.getBoundingClientRect(); if (duration) seek(Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * duration) }}>
      {peaks.length ? peaks.map((peak, index) => <i key={index} className={index / peaks.length <= position / duration ? 'is-played' : ''} style={{ height: `${Math.max(4, peak * 100)}%` }} />) : <span>{duration ? '音频已就绪' : '正在读取音频…'}</span>}
    </div>
    <input aria-label="音频播放进度" type="range" min={0} max={duration || 1} step={.01} value={position} disabled={!duration} onChange={(event) => seek(Number(event.target.value))} />
    <div className="pf-audio-controls"><button aria-label={playing ? '暂停音频' : '播放音频'} disabled={!duration} onClick={() => { if (!audio.current) return; if (playing) audio.current.pause(); else void audio.current.play().catch(() => setError('无法播放此音频格式')) }}>{playing ? <Pause size={16} /> : <Play size={16} />}</button><span>{timeLabel(position)} / {timeLabel(duration)}</span><select aria-label="音频播放速度" value={speed} onChange={(event) => { const value = Number(event.target.value); setSpeed(value); if (audio.current) audio.current.playbackRate = value }}>{[.5, .75, 1, 1.25, 1.5, 2].map((value) => <option key={value} value={value}>{value}×</option>)}</select><button aria-label={volume ? '静音音频' : '取消音频静音'} onClick={() => { const value = volume ? 0 : 1; setVolume(value); if (audio.current) audio.current.volume = value }}>{volume ? <Volume2 size={15} /> : <VolumeX size={15} />}</button><input aria-label="音频音量" type="range" min={0} max={1} step={.05} value={volume} onChange={(event) => { const value = Number(event.target.value); setVolume(value); if (audio.current) audio.current.volume = value }} /></div>
    {error && <span role="status">{error}</span>}
  </div>
}
