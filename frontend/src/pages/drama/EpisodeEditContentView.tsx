/** 分镜正文只读渲染：把 @asset:id 显示为带缩略图的关联标签 */
import { Fragment, useMemo } from 'react'
import { resolveDramaMediaUrl, type DramaAsset } from '../../api/drama'

type Props = {
  content: string
  assets: DramaAsset[]
  onOpenAsset?: (assetId: number) => void
}

type Part =
  | { kind: 'text'; text: string }
  | { kind: 'asset'; assetId: number }

const ASSET_TOKEN = /@asset:(\d+)/g

// 将正文拆成文本与资产引用片段
function splitContentParts(content: string): Part[] {
  const parts: Part[] = []
  let last = 0
  const re = new RegExp(ASSET_TOKEN.source, 'g')
  let m: RegExpExecArray | null
  while ((m = re.exec(content))) {
    if (m.index > last) {
      parts.push({ kind: 'text', text: content.slice(last, m.index) })
    }
    parts.push({ kind: 'asset', assetId: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < content.length) {
    parts.push({ kind: 'text', text: content.slice(last) })
  }
  return parts
}

// 渲染只读正文（关联标签可视化）
export function EpisodeEditContentView({ content, assets, onOpenAsset }: Props) {
  const byId = useMemo(() => new Map(assets.map((a) => [a.id, a])), [assets])
  const parts = useMemo(() => splitContentParts(content || ''), [content])

  if (!content.trim()) {
    return <p className="drama-ep-content-empty">暂无脚本内容，点击「编辑」开始填写</p>
  }

  return (
    <div className="drama-ep-content-view">
      {parts.map((part, idx) => {
        if (part.kind === 'text') {
          return (
            <Fragment key={`t-${idx}`}>
              {part.text.split('\n').map((line, lineIdx, arr) => (
                <Fragment key={`l-${idx}-${lineIdx}`}>
                  {line}
                  {lineIdx < arr.length - 1 ? <br /> : null}
                </Fragment>
              ))}
            </Fragment>
          )
        }
        const asset = byId.get(part.assetId)
        const preview = asset ? resolveDramaMediaUrl(asset.cover || asset.url) : ''
        const label = asset?.name || `资产 ${part.assetId}`
        return (
          <button
            key={`a-${idx}-${part.assetId}`}
            type="button"
            className="drama-ep-mention-chip"
            title={`@asset:${part.assetId} · ${label}`}
            onClick={() => onOpenAsset?.(part.assetId)}
          >
            {preview ? (
              <img src={preview} alt="" draggable={false} />
            ) : (
              <span className="drama-ep-mention-chip-fallback">{label[0]}</span>
            )}
            <span className="drama-ep-mention-chip-label">{label}</span>
          </button>
        )
      })}
    </div>
  )
}
