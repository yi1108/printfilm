/** 漫剧画面风格预览图：按 jpg → png → 后端 static → svg 依次回退 */
import { useMemo, useState } from 'react'
import { getDramaImageStylePreviewCandidates } from '../../lib/dramaImageStylePreviews'
import type { ImageStyleId } from '../../lib/dramaImageStyles'

type Props = {
  styleId: ImageStyleId
  alt?: string
  className?: string
  loading?: 'lazy' | 'eager'
}

// 渲染带多级回退的风格预览图
export function DramaImageStylePreviewImg({
  styleId,
  alt = '',
  className,
  loading = 'lazy',
}: Props) {
  const candidates = useMemo(() => getDramaImageStylePreviewCandidates(styleId), [styleId])
  const [index, setIndex] = useState(0)

  return (
    <img
      key={`${styleId}-${index}`}
      src={candidates[Math.min(index, candidates.length - 1)]}
      alt={alt}
      className={className}
      loading={loading}
      onError={() => {
        setIndex((current) => (current < candidates.length - 1 ? current + 1 : current))
      }}
    />
  )
}
