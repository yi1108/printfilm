import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useRef, useState } from 'react'
import { request, upload } from './api'
import { CheckCircle2, UploadCloud } from 'lucide-react'
import AssetPreview, { PreviewContent } from './AssetPreview'
import { explainMarketplaceError } from './messages'

// 上传状态与“处理就绪”分开显示，只允许绑定 ready 文件。locked 时不提供手动选择。
export default function AssetPicker({ kind, value, onChange, title = mt("选择或上传文件"), required = false, locked = false }: { kind: 'video' | 'document' | 'image'; value: number | null; onChange: (id: number) => void; title?: string; required?: boolean; locked?: boolean }) {
  useMarketplaceLocale()
  /* 仅上传并绑定当前文件，不加载历史文件列表。 */


  const [error, setError] = useState('')
  const [progress, setProgress] = useState<number | null>(null)

  const [pending, setPending] = useState<number | null>(null)
  const controller = useRef<AbortController | null>(null)
  const [localFile, setLocalFile] = useState<File | null>(null)
  const [localAssetId, setLocalAssetId] = useState<number | null>(null)
  const [localUrl, setLocalUrl] = useState('')
  // Preview is optional browser feedback, never a prerequisite for uploading.
  const waitingPreview = locked
  useEffect(() => {
    if (!localFile) { setLocalUrl(''); return }
    const url = URL.createObjectURL(localFile); setLocalUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [localFile])
  useEffect(() => {
    if (!pending) return
    let active = true
    // 独立查询处理状态，离开页面即清理轮询。
    const check = async () => {
      try {
        const asset = await request<{ status: string; error: string }>(`/assets/${pending}`)
        if (!active) return
        if (asset.status === 'ready') { onChange(pending); setPending(null); setProgress(null) }
        if (asset.status === 'failed') { setError(asset.error ? explainMarketplaceError(asset.error) : mt("文件校验失败，请检查文件后重试。")); setPending(null); setProgress(null) }
      } catch (e) { if (active) { setError((e as Error).message); setPending(null); setProgress(null) } }
    }
    const interval = window.setInterval(check, 5000); void check()
    return () => { active = false; window.clearInterval(interval) }
  }, [pending, onChange])
  // 续传失败保留会话，重新选择同一文件即可继续。
  async function choose(file?: File) {
    if (!file) return
    const allowed = kind === 'video' ? /\.(mp4|mov|webm)$/i : kind === 'image' ? /\.(png|jpe?g|webp)$/i : /\.(pdf|png|jpe?g|webp)$/i
    if (file.size === 0) { setError(mt("文件为空，请重新选择。")); return }
    if (!allowed.test(file.name)) { setError(kind === 'video' ? mt("请选择 MP4、MOV 或 WebM 视频。") : kind === 'image' ? mt("请选择 PNG、JPG 或 WebP 图片。") : mt("请选择 PDF、PNG、JPG 或 WebP 文件。")); return }
    if (file.size > (kind === 'video' ? 500 : 20) * 1024 * 1024) { setError(kind === 'video' ? mt("视频不能超过 500MB，请选择较小的视频。") : mt("文件不能超过 20MB，请选择较小的文件。")); return }
    setLocalFile(file); setLocalAssetId(null)
    setError(''); setProgress(0)
    controller.current = new AbortController()
    try { const id = await upload(file, kind, setProgress, controller.current.signal); setLocalAssetId(id); onChange(id); setPending(id) }
    catch (e) { setError((e as Error).message); setProgress(null) }
    finally { controller.current = null }
  }
  return <fieldset><legend>{title}{required && <span className="pf-req-mark">{mt("必填")}</span>}</legend>
    {waitingPreview ? <p className="pf-market-notice" role="status">{mt("正在同步成片…")}</p> : <label className="pf-market-upload-zone"><UploadCloud size={28} strokeWidth={1.4} /><strong>{mt("点击选择")}{kind === 'video' ? mt("视频") : kind === 'image' ? mt("图片") : mt("文件")}</strong><span>{kind === 'video' ? mt("MP4 / MOV / WebM · 最大500MB · 最长30分钟") : kind === 'image' ? mt("PNG / JPG / WebP · 最大20MB") : mt("PDF / PNG / JPG / WebP · 最大20MB")}</span><input aria-label={mt("上传{0}", [title])} type="file" disabled={progress !== null} accept={kind === 'video' ? '.mp4,.mov,.webm' : kind === 'image' ? '.png,.jpg,.jpeg,.webp' : '.pdf,.png,.jpg,.jpeg,.webp'} onChange={e => { void choose(e.target.files?.[0]); e.target.value = '' }} /></label>}
    {!waitingPreview && progress !== null && <div className="pf-market-upload-progress" role="status"><p>{pending ? mt("上传完成，正在确认文件状态，预览会自动更新。") : mt("正在上传 {0}%", [progress])}</p><progress value={progress} max={100} aria-label={mt("上传进度")} /></div>}
    {!waitingPreview && progress !== null && !pending && <button type="button" onClick={() => controller.current?.abort()}>{mt("取消上传")}</button>}
    {localFile && localUrl && <div><p>{mt("本地预览：")}{localFile.name} · {(localFile.size / 1024 / 1024).toFixed(2)} MB</p><p>{mt("仅供检查所选文件，不代表已上传或审核通过。")}</p><PreviewContent key={localUrl} url={localUrl} filename={localFile.name} video={kind === 'video'} /><button type="button" onClick={() => setLocalFile(null)}>{mt("关闭本地预览")}</button></div>}
    {value && <><p className="pf-market-upload-selection" hidden={waitingPreview}><CheckCircle2 size={14} />  {mt("当前")}{kind === 'video' ? mt("视频") : kind === 'image' ? mt("图片") : mt("文件")}{mt("已选择，文件名和状态见下方。")}</p><AssetPreview key={value} id={value} hideMedia={Boolean(localFile)} onReady={id => { if (id === localAssetId) { setLocalFile(null); setLocalAssetId(null) } }} /></>}{error && <p role="alert">{marketFeedback(error)}</p>}</fieldset>
}

