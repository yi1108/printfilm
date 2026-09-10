/** 分镜条规格标签：优先展示成片真实像素，legacy 无 meta 时探测 video 元数据 */
import { useEffect, useState } from 'react'
import {
  formatProjectOutputLabel,
  inferAspectRatioFromPixels,
  pickDramaResolution,
  readFragmentOutputLabel,
  readFragmentVideoDimensions,
} from '../../lib/dramaProjectOutputSettings'
import { probeVideoDimensionsFromUrl } from '../../lib/dramaVideoDimensions'

type DramaFragmentClipSpecProps = {
  fragmentParams: Record<string, unknown>
  episodeParams: Record<string, unknown>
  projectParams: Record<string, unknown>
  videoUrl?: string
}

// 渲染单个分镜的画幅 · 清晰度标签
export function DramaFragmentClipSpec({
  fragmentParams,
  episodeParams,
  projectParams,
  videoUrl = '',
}: DramaFragmentClipSpecProps) {
  const stored = readFragmentVideoDimensions(fragmentParams)
  const [probed, setProbed] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    if (stored || !videoUrl.trim()) {
      setProbed(null)
      return
    }
    let cancelled = false
    void probeVideoDimensionsFromUrl(videoUrl).then((dims) => {
      if (!cancelled) setProbed(dims)
    })
    return () => {
      cancelled = true
    }
  }, [stored, videoUrl])

  const dims = stored ?? probed
  const resolution = pickDramaResolution(fragmentParams, episodeParams, projectParams)
  const label = dims
    ? formatProjectOutputLabel(inferAspectRatioFromPixels(dims.w, dims.h), resolution)
    : readFragmentOutputLabel(fragmentParams, episodeParams, projectParams)

  return <span className="drama-ep-clip-spec">{label}</span>
}
