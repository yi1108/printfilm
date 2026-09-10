/** 浏览器端探测视频真实宽高（legacy 分镜无 params 时使用） */
export function probeVideoDimensionsFromUrl(
  url: string,
): Promise<{ w: number; h: number } | null> {
  return new Promise((resolve) => {
    if (!url.trim()) {
      resolve(null)
      return
    }
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.muted = true
    const cleanup = () => {
      video.removeAttribute('src')
      video.load()
    }
    video.onloadedmetadata = () => {
      const w = video.videoWidth
      const h = video.videoHeight
      cleanup()
      resolve(w > 0 && h > 0 ? { w, h } : null)
    }
    video.onerror = () => {
      cleanup()
      resolve(null)
    }
    video.src = url
  })
}
