import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { printfilmStudioApi } from '../api'
import type { ProjectAsset } from '../types'
import { gridTiles } from './gridSplit'
import { readProjectMedia } from './projectMedia'

export function GridSplitEditor({ projectId, assetId, url, title, headers, onClose, onComplete }: {
  projectId: number; assetId?: number; url: string; title: string; headers: HeadersInit; onClose: () => void; onComplete: (assets: ProjectAsset[], columns: number) => void
}) {
  const [rows, setRows] = useState(3), [columns, setColumns] = useState(3)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [busy, setBusy] = useState(false), [completed, setCompleted] = useState(0), [error, setError] = useState('')
  const abort = useRef<AbortController | null>(null)
  useEffect(() => () => abort.current?.abort(), [url])
  let valid = false
  try { gridTiles(size.width, size.height, rows, columns); valid = true } catch { /* preview awaits metadata */ }
  const split = async () => {
    if (busy || !valid) return
    const controller = new AbortController(); abort.current = controller
    setBusy(true); setError(''); setCompleted(0)
    let bitmap: ImageBitmap | undefined
    const outputs: ProjectAsset[] = []
    try {
      bitmap = await createImageBitmap(await readProjectMedia(url, projectId, assetId, controller.signal))
      const tiles = gridTiles(bitmap.width, bitmap.height, rows, columns)
      const canvas = window.document.createElement('canvas'), context = canvas.getContext('2d')
      if (!context) throw new Error('当前浏览器无法处理图片')
      for (const tile of tiles) {
        controller.signal.throwIfAborted()
        canvas.width = tile.width; canvas.height = tile.height
        context.drawImage(bitmap, tile.x, tile.y, tile.width, tile.height, 0, 0, tile.width, tile.height)
        const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error('切分图片编码失败')), 'image/png'))
        outputs.push(await printfilmStudioApi.uploadAsset(projectId, new File([blob], `${title}-${tile.row + 1}-${tile.column + 1}.png`, { type: 'image/png' }), headers, controller.signal))
        controller.signal.throwIfAborted(); setCompleted(outputs.length)
      }
      onComplete(outputs, columns); onClose()
    } catch (reason) { if (!controller.signal.aborted) setError(`${reason instanceof Error ? reason.message : '切分失败'}${outputs.length ? `，已完成的 ${outputs.length} 张保留在素材库中` : ''}`) }
    finally { bitmap?.close(); if (!controller.signal.aborted) setBusy(false) }
  }
  return <div className="pf-edit-overlay"><section className="pf-grid-split" role="dialog" aria-modal="true" aria-label="宫格切分"><header><b>宫格切分</b><span>保留原图</span><button aria-label="关闭宫格切分" onClick={onClose}><X size={18} /></button></header>
    <div className="pf-grid-presets">{[2, 3, 4, 5].map((count) => <button disabled={busy} key={count} aria-pressed={rows === count && columns === count} onClick={() => { setRows(count); setColumns(count) }}><span style={{ display: 'grid', gridTemplateColumns: `repeat(${count},1fr)` }}>{Array.from({ length: count * count }, (_, i) => <i key={i} />)}</span>{count * count} 宫格<small>{count} × {count}</small></button>)}</div>
    <div className="pf-grid-dimensions"><label>行数<input aria-label="切分行数" disabled={busy} type="number" min="1" max="10" value={rows} onChange={(event) => setRows(Number(event.target.value))} /></label><span>×</span><label>列数<input aria-label="切分列数" disabled={busy} type="number" min="1" max="10" value={columns} onChange={(event) => setColumns(Number(event.target.value))} /></label></div>
    <div className="pf-grid-preview"><img src={url} alt="宫格切分预览" onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} onError={() => setError('原图无法加载')} />{valid && <div style={{ gridTemplateColumns: `repeat(${columns},1fr)`, gridTemplateRows: `repeat(${rows},1fr)` }}>{Array.from({ length: rows * columns }, (_, i) => <span key={i}>{i + 1}</span>)}</div>}</div>
    <p>从左到右，逐行切分，共 {valid ? rows * columns : '—'} 张。切分后放到原图右侧。</p>{error && <p role="alert">{error}</p>}
    <button className="pf-grid-submit" disabled={busy || !valid} onClick={() => void split()}>{busy ? `正在切分 ${completed} / ${rows * columns}` : '切分为图片节点'}</button>
  </section></div>
}
