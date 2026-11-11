import { useEffect, useRef, useState } from 'react'
import { Download, Film, X } from 'lucide-react'
import { printfilmStudioApi } from '../api'
import type { FrameAnalysisReport, ProjectAsset } from '../types'
import './frameAnalysis.css'
import { readProjectMedia } from './projectMedia'

export function FrameAnalysisEditor({ projectId, assetId, url, report, headers, writable, onClose, onComplete }: { projectId: number; assetId?: number; url: string; report?: FrameAnalysisReport; headers: HeadersInit; writable: boolean; onClose: () => void; onComplete: (report: FrameAnalysisReport, assets: ProjectAsset[]) => void }) {
  const [result, setResult] = useState(report)
  const [detector, setDetector] = useState<'adaptive' | 'content'>(report?.detector || 'adaptive')
  const [threshold, setThreshold] = useState(report?.threshold || 3)
  const [minimum, setMinimum] = useState(report?.minimum || .6)
  const [frames, setFrames] = useState(true), [clips, setClips] = useState(true), [audio, setAudio] = useState(true)
  const [selected, setSelected] = useState(0), [mode, setMode] = useState<'frame' | 'clip'>('frame')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const analyze = async () => {
    if (controller.current || !writable) return
    const abort = new AbortController(); controller.current = abort; setBusy(true); setError('')
    try {
      const blob = await readProjectMedia(url, projectId, assetId, abort.signal)
      if (blob.size > 100 * 1024 * 1024) throw new Error('源视频不能超过 100MB')
      const output = await printfilmStudioApi.analyzeMedia(projectId, new File([blob], 'source.media', { type: blob.type }), { detector, threshold, minimum, frames, clips, audio }, headers, abort.signal)
      if (!abort.signal.aborted) { setResult(output.report); setSelected(0); setMode(frames ? 'frame' : 'clip'); onComplete(output.report, output.assets) }
    } catch (reason) { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '分析失败') }
    finally { if (controller.current === abort) { controller.current = null; setBusy(false) } }
  }
  const download = () => {
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = objectUrl; link.download = '分镜分析.json'; link.click(); setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
  const shot = result?.shots[selected], preview = mode === 'clip' ? shot?.clip : shot?.frame
  return <div className="pf-edit-overlay"><section className="pf-frame-analysis" role="dialog" aria-modal="true" aria-label="逐帧拉片">
    <header><b><Film size={18} /> 逐帧拉片</b><button aria-label="关闭逐帧拉片" onClick={() => { controller.current?.abort(); onClose() }}><X size={18} /></button></header>
    <fieldset disabled={busy || !writable} className="pf-analysis-settings">
      <label>检测方式<select aria-label="检测方式" value={detector} onChange={(event) => { const value = event.target.value as 'adaptive' | 'content'; setDetector(value); setThreshold(value === 'adaptive' ? 3 : .28) }}><option value="adaptive">自适应 · 适合运动镜头</option><option value="content">内容变化 · 适合硬切</option></select></label>
      <label>变化阈值<input aria-label="变化阈值" type="number" min={.01} max={detector === 'adaptive' ? 10 : 1} step={detector === 'adaptive' ? .1 : .01} value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label>
      <label>最短镜头（秒）<input aria-label="最短镜头时长" type="number" min={.1} max={60} step={.1} value={minimum} onChange={(event) => setMinimum(Number(event.target.value))} /></label>
      <label><input type="checkbox" checked={frames} onChange={(event) => setFrames(event.target.checked)} />分镜图</label><label><input type="checkbox" checked={clips} onChange={(event) => setClips(event.target.checked)} />动态片段</label><label><input type="checkbox" checked={audio} onChange={(event) => setAudio(event.target.checked)} />原音轨</label>
    </fieldset>
    <div className="pf-analysis-content">
      {result ? <><nav aria-label="检测出的镜头">{result.shots.map((item, index) => <button key={item.index} className={selected === index ? 'is-active' : ''} onClick={() => setSelected(index)}>{item.frame?.url && <img src={item.frame.url} alt="" />}<span><b>镜头 {item.index}</b><small>{item.start.toFixed(2)}–{item.end.toFixed(2)} 秒 · {item.duration.toFixed(2)} 秒</small></span></button>)}</nav><main><div className="pf-analysis-tabs"><button className={mode === 'frame' ? 'is-active' : ''} disabled={!shot?.frame} onClick={() => setMode('frame')}>分镜图</button><button className={mode === 'clip' ? 'is-active' : ''} disabled={!shot?.clip} onClick={() => setMode('clip')}>动态片段</button><button onClick={download}><Download size={14} /> 下载报告</button></div>{preview?.url ? mode === 'clip' ? <video key={preview.url} controls src={preview.url} /> : <img src={preview.url} alt={`镜头 ${shot?.index} 中间帧`} /> : <p>未导出此类媒体，可修改选项后重新分析。</p>}{result.audio?.url && <label>完整原音轨<audio controls src={result.audio.url} /></label>}{!result.has_audio && <p>源视频不含音轨。</p>}</main></> : <main><video src={url} controls /><p>按镜头变化切分视频，每个镜头提取中间帧；动态片段保留原声。</p></main>}
    </div>
    {error && <p role="alert" className="pf-editor-error">{error}</p>}
    <footer><span>{result ? `${result.shots.length} 个镜头 · ${result.duration.toFixed(2)} 秒` : '本地分析 · 无模型调用费用 · ≤ 100MB / 10 分钟'}</span>{busy ? <button onClick={() => controller.current?.abort()}>取消分析</button> : writable && <button className="is-primary" disabled={!url || threshold <= 0 || minimum < .1 || minimum > 60 || threshold > (detector === 'content' ? 1 : 10)} onClick={() => void analyze()}>{result ? '重新分析' : '开始拉片'}</button>}</footer>
  </section></div>
}
