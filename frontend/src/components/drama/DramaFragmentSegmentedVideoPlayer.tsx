/** 分集编辑：带分镜分段进度条的视频播放器（客户端顺序连播） */
import { Download, Maximize, Minimize, MonitorPlay, Pause, Play, Volume2, VolumeX } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { resolveDramaMediaUrl, type DramaFragment } from '../../api/drama'
import {
  buildEpisodeVideoTimelineSegments,
  formatVideoTimelineClock,
  resolveEpisodeTimelineSegmentFillRatio,
  resolveEpisodeVideoTimelineTotalDuration,
  resolveFragmentPlaybackFromGlobalTime,
  resolveGlobalTimeFromFragmentPlayback,
  resolveNextPlayableFragmentId,
  resolveVideoTimelineSeekTime,
  type DramaEpisodeVideoTimelineSegment,
} from '../../lib/dramaEpisodeVideoTimeline'

type Props = {
  fragments: DramaFragment[]
  playingFragmentId: number | null
  onPlayingFragmentChange: (fragmentId: number) => void
  aspectRatio: string
  /** 预览历史版本时覆盖当前镜视频地址 */
  overrideVideoUrl?: string | null
  overridePosterUrl?: string | null
}

// 渲染带分镜分段进度条的视频播放器
export function DramaFragmentSegmentedVideoPlayer({
  fragments,
  playingFragmentId,
  onPlayingFragmentChange,
  aspectRatio,
  overrideVideoUrl = null,
  overridePosterUrl = null,
}: Props) {
  // videoRef 视频元素引用
  const videoRef = useRef<HTMLVideoElement | null>(null)
  // screenRef 预览画面容器（全屏目标）
  const screenRef = useRef<HTMLDivElement | null>(null)
  // trackRef 分段进度条容器引用
  const trackRef = useRef<HTMLDivElement | null>(null)
  // isSeeking 是否正在拖动进度条
  const isSeekingRef = useRef(false)
  // autoLinkNextRef 是否自动衔接下一片段
  const autoLinkNextRef = useRef(true)
  // playingFragmentIdRef 当前播放分镜 ID
  const playingFragmentIdRef = useRef(playingFragmentId)
  // timelineSegmentsRef 时间轴分段缓存
  const timelineSegmentsRef = useRef(buildEpisodeVideoTimelineSegments(fragments))
  // shouldResumePlayRef 切换分镜后是否继续播放
  const shouldResumePlayRef = useRef(false)
  // pendingSeekTimeRef 切换分镜后待跳转的本地时间
  const pendingSeekTimeRef = useRef<number | null>(null)
  // autoPlayAttemptedRef 当前视频是否已尝试自动播放
  const autoPlayAttemptedRef = useRef(false)
  // playingSegmentRef 当前播放区间（供事件回调读取，避免轮询刷新 fragments 重绑事件）
  const playingSegmentRef = useRef<DramaEpisodeVideoTimelineSegment | null>(null)
  // prevPlayingFragmentIdRef 上次已处理的分镜切换
  const prevPlayingFragmentIdRef = useRef<number | null>(playingFragmentId)
  // isPlaying 是否正在播放
  const [isPlaying, setIsPlaying] = useState(false)
  // globalCurrentTime 全局时间轴当前位置（秒）
  const [globalCurrentTime, setGlobalCurrentTime] = useState(0)
  // autoLinkNext 当前片段播完后自动播放下一片段
  const [autoLinkNext, setAutoLinkNext] = useState(true)
  // muted 是否静音
  const [muted, setMuted] = useState(false)
  // isFullscreen 预览是否处于全屏
  const [isFullscreen, setIsFullscreen] = useState(false)

  playingFragmentIdRef.current = playingFragmentId
  autoLinkNextRef.current = autoLinkNext

  // timelineSegments 分集全部分镜时间轴分段
  const timelineSegments = useMemo(
    () => buildEpisodeVideoTimelineSegments(fragments),
    [fragments],
  )

  timelineSegmentsRef.current = timelineSegments

  // totalDuration 分集时间轴总时长
  const totalDuration = useMemo(
    () => resolveEpisodeVideoTimelineTotalDuration(timelineSegments),
    [timelineSegments],
  )

  // playingFragment 当前播放分镜
  const playingFragment = useMemo(
    () => fragments.find((fragment) => fragment.id === playingFragmentId) ?? null,
    [fragments, playingFragmentId],
  )

  // playingSegment 当前播放分镜在时间轴上的区间
  const playingSegment = useMemo(
    () => timelineSegments.find((segment) => segment.fragmentId === playingFragmentId) ?? null,
    [playingFragmentId, timelineSegments],
  )

  playingSegmentRef.current = playingSegment

  // videoUrl 当前分镜视频地址（可被历史版本预览覆盖）
  const videoUrl =
    overrideVideoUrl ||
    (playingFragment?.video ? resolveDramaMediaUrl(playingFragment.video) : null)
  // posterUrl 当前分镜封面地址
  const posterUrl =
    overridePosterUrl ||
    (playingFragment?.cover ? resolveDramaMediaUrl(playingFragment.cover) : null)
  // hasCurrentVideo 当前分镜是否可播放
  const hasCurrentVideo = Boolean(videoUrl)
  // hasAnyVideo 是否存在任一分镜视频
  const hasAnyVideo = timelineSegments.some((segment) => segment.hasVideo)

  // ratioClass 画幅 CSS 类名
  const ratioClass = `ratio-${aspectRatio.replace(':', 'x')}`

  // 切换播放或暂停
  const handleTogglePlay = useCallback(() => {
    const video = videoRef.current

    if (!video || !hasCurrentVideo) {
      return
    }

    if (video.paused) {
      void video.play().catch(() => undefined)
      return
    }

    video.pause()
  }, [hasCurrentVideo])

  // 跳转到全局时间轴位置
  const seekToGlobalTime = useCallback(
    (globalTimeSec: number) => {
      const playback = resolveFragmentPlaybackFromGlobalTime(timelineSegments, globalTimeSec)

      if (!playback) {
        return
      }

      setGlobalCurrentTime(
        resolveGlobalTimeFromFragmentPlayback(
          playback.segment,
          playback.localTimeSec,
          playback.segment.durationSec,
        ),
      )

      if (playback.segment.fragmentId !== playingFragmentIdRef.current) {
        pendingSeekTimeRef.current = playback.localTimeSec
        shouldResumePlayRef.current = isPlaying
        onPlayingFragmentChange(playback.segment.fragmentId)
        return
      }

      const video = videoRef.current

      if (video && hasCurrentVideo) {
        video.currentTime = playback.localTimeSec
      }
    },
    [hasCurrentVideo, isPlaying, onPlayingFragmentChange, timelineSegments],
  )

  // 根据点击位置跳转播放进度
  const seekByClientX = useCallback(
    (clientX: number) => {
      const track = trackRef.current

      if (!track || totalDuration <= 0) {
        return
      }

      const rect = track.getBoundingClientRect()
      const ratio = (clientX - rect.left) / rect.width
      const nextGlobalTime = resolveVideoTimelineSeekTime(ratio, totalDuration)

      seekToGlobalTime(nextGlobalTime)
    },
    [seekToGlobalTime, totalDuration],
  )

  // 绑定视频事件（仅在当前视频地址变化时重置）
  useEffect(() => {
    const video = videoRef.current

    if (!video || !videoUrl) {
      return
    }

    autoPlayAttemptedRef.current = false

    const tryAutoPlay = () => {
      if (autoPlayAttemptedRef.current) {
        return
      }

      autoPlayAttemptedRef.current = true

      if (shouldResumePlayRef.current) {
        void video.play().catch(() => undefined)
        shouldResumePlayRef.current = false
      }
    }

    const handleLoadedMetadata = () => {
      if (pendingSeekTimeRef.current !== null) {
        video.currentTime = pendingSeekTimeRef.current
        pendingSeekTimeRef.current = null
      }
    }

    const handleDurationChange = () => {
      if (pendingSeekTimeRef.current !== null) {
        video.currentTime = pendingSeekTimeRef.current
        pendingSeekTimeRef.current = null
      }
    }

    const handleCanPlay = () => {
      if (pendingSeekTimeRef.current !== null) {
        video.currentTime = pendingSeekTimeRef.current
        pendingSeekTimeRef.current = null
      }

      tryAutoPlay()
    }

    const handleTimeUpdate = () => {
      const segment = playingSegmentRef.current

      if (isSeekingRef.current || !segment) {
        return
      }

      const nextGlobalTime = resolveGlobalTimeFromFragmentPlayback(
        segment,
        video.currentTime,
        Number.isFinite(video.duration) ? video.duration : segment.durationSec,
      )

      setGlobalCurrentTime(nextGlobalTime)
    }

    const handlePlay = () => {
      setIsPlaying(true)
    }

    const handlePause = () => {
      setIsPlaying(false)
    }

    const handleEnded = () => {
      if (!autoLinkNextRef.current) {
        setIsPlaying(false)
        return
      }

      const nextFragmentId = resolveNextPlayableFragmentId(
        timelineSegmentsRef.current,
        playingFragmentIdRef.current ?? 0,
      )

      if (!nextFragmentId) {
        setIsPlaying(false)
        return
      }

      shouldResumePlayRef.current = true
      onPlayingFragmentChange(nextFragmentId)
    }

    video.addEventListener('timeupdate', handleTimeUpdate)
    video.addEventListener('loadedmetadata', handleLoadedMetadata)
    video.addEventListener('durationchange', handleDurationChange)
    video.addEventListener('canplay', handleCanPlay)
    video.addEventListener('play', handlePlay)
    video.addEventListener('pause', handlePause)
    video.addEventListener('ended', handleEnded)

    if (video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
      tryAutoPlay()
    }

    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate)
      video.removeEventListener('loadedmetadata', handleLoadedMetadata)
      video.removeEventListener('durationchange', handleDurationChange)
      video.removeEventListener('canplay', handleCanPlay)
      video.removeEventListener('play', handlePlay)
      video.removeEventListener('pause', handlePause)
      video.removeEventListener('ended', handleEnded)
    }
  }, [onPlayingFragmentChange, videoUrl])

  // 仅在用户切换分镜时重置到该分镜起点（生成轮询刷新 fragments 不应打断播放）
  useEffect(() => {
    if (playingFragmentId === prevPlayingFragmentIdRef.current) {
      return
    }

    prevPlayingFragmentIdRef.current = playingFragmentId

    if (!playingSegment) {
      setGlobalCurrentTime(0)
      return
    }

    if (shouldResumePlayRef.current || pendingSeekTimeRef.current !== null) {
      return
    }

    setGlobalCurrentTime(playingSegment.startSec)

    const video = videoRef.current

    if (video && videoUrl) {
      video.pause()
      video.currentTime = 0
      setIsPlaying(false)
    }
  }, [playingFragmentId, playingSegment, videoUrl])

  useEffect(() => {
    const video = videoRef.current

    if (!video) {
      return
    }

    video.muted = muted
  }, [muted])

  // 同步浏览器全屏状态
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === screenRef.current)
    }

    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  // 切换预览画面全屏
  const handleToggleFullscreen = useCallback(async () => {
    const screen = screenRef.current

    if (!screen || !hasCurrentVideo) {
      return
    }

    try {
      if (document.fullscreenElement === screen) {
        await document.exitFullscreen()
        return
      }

      await screen.requestFullscreen()
    } catch {
      /* 浏览器可能拒绝全屏 */
    }
  }, [hasCurrentVideo])

  // 下载当前分镜视频
  const handleDownloadVideo = useCallback(() => {
    if (!videoUrl) {
      return
    }

    const link = document.createElement('a')

    link.href = videoUrl
    link.download = ''
    link.rel = 'noopener noreferrer'
    link.target = '_blank'
    link.click()
  }, [videoUrl])

  // playheadLeft 播放指针横向位置百分比
  const playheadLeft = totalDuration > 0 ? (globalCurrentTime / totalDuration) * 100 : 0

  return (
    <div className="drama-ep-segmented-player">
      <div
        ref={screenRef}
        className={`drama-ep-player drama-ep-segmented-screen ${ratioClass}${
          !hasCurrentVideo ? ' is-empty' : ''
        }${isFullscreen ? ' is-fullscreen' : ''}`}
      >
        {hasCurrentVideo ? (
          <>
            <video
              ref={videoRef}
              src={videoUrl ?? undefined}
              poster={posterUrl ?? undefined}
              playsInline
              preload="auto"
            />
            <div className="drama-ep-video-overlay-actions">
              <button
                type="button"
                aria-label={isFullscreen ? '退出全屏' : '全屏预览'}
                className="drama-ep-video-overlay-btn"
                onClick={() => void handleToggleFullscreen()}
              >
                {isFullscreen ? (
                  <Minimize size={16} strokeWidth={1.8} />
                ) : (
                  <Maximize size={16} strokeWidth={1.8} />
                )}
              </button>
              <button
                type="button"
                aria-label="下载视频"
                className="drama-ep-video-overlay-btn"
                onClick={handleDownloadVideo}
              >
                <Download size={16} strokeWidth={1.8} />
              </button>
            </div>
          </>
        ) : posterUrl ? (
          <img src={posterUrl} alt="分镜预览" />
        ) : (
          <div className="drama-ep-player-placeholder">
            <span>视频待生成</span>
          </div>
        )}
      </div>

      <div className="drama-ep-video-controls">
        <p className="drama-ep-video-clock">
          {formatVideoTimelineClock(globalCurrentTime)} / {formatVideoTimelineClock(totalDuration)}
        </p>

        <div className="drama-ep-video-toolbar">
          <button
            type="button"
            aria-label={isPlaying ? '暂停' : '播放'}
            disabled={!hasCurrentVideo}
            className="drama-ep-video-icon-btn"
            onClick={handleTogglePlay}
          >
            {isPlaying ? (
              <Pause size={16} strokeWidth={2} />
            ) : (
              <Play size={16} strokeWidth={2} />
            )}
          </button>

          <div
            ref={trackRef}
            className={`drama-ep-video-track${totalDuration <= 0 ? ' is-disabled' : ''}`}
            onPointerDown={(event) => {
              if (totalDuration <= 0) {
                return
              }

              isSeekingRef.current = true
              seekByClientX(event.clientX)
            }}
            onPointerMove={(event) => {
              if (totalDuration <= 0 || !isSeekingRef.current) {
                return
              }

              seekByClientX(event.clientX)
            }}
            onPointerUp={() => {
              isSeekingRef.current = false
            }}
            onPointerLeave={() => {
              isSeekingRef.current = false
            }}
          >
            {timelineSegments.map((segment, index) => (
              <div
                key={segment.fragmentId}
                className={`drama-ep-video-track-seg${
                  index < timelineSegments.length - 1 ? ' has-divider' : ''
                }`}
                style={{ flex: segment.durationSec }}
              >
                <div
                  className="drama-ep-video-track-fill"
                  style={{
                    width: `${resolveEpisodeTimelineSegmentFillRatio(segment, globalCurrentTime) * 100}%`,
                  }}
                />
              </div>
            ))}

            <div className="drama-ep-video-playhead" style={{ left: `${playheadLeft}%` }} />
          </div>

          <button
            type="button"
            aria-label={autoLinkNext ? '关闭自动衔接下一片段' : '开启自动衔接下一片段'}
            title={
              autoLinkNext ? '关闭自动衔接下一片段' : '当前片段播放完后自动播放下一片段'
            }
            disabled={!hasAnyVideo}
            className={`drama-ep-video-autolink${autoLinkNext ? ' is-on' : ''}`}
            onClick={() => setAutoLinkNext((value) => !value)}
          >
            <MonitorPlay size={16} strokeWidth={1.8} />
            <span className="drama-ep-video-autolink-bar" />
          </button>

          <button
            type="button"
            aria-label={muted ? '取消静音' : '静音'}
            disabled={!hasCurrentVideo}
            className="drama-ep-video-icon-btn is-muted"
            onClick={() => setMuted((value) => !value)}
          >
            {muted ? (
              <VolumeX size={16} strokeWidth={1.8} />
            ) : (
              <Volume2 size={16} strokeWidth={1.8} />
            )}
          </button>

          <button
            type="button"
            aria-label={isFullscreen ? '退出全屏' : '全屏预览'}
            title={isFullscreen ? '退出全屏' : '全屏预览'}
            disabled={!hasCurrentVideo}
            className="drama-ep-video-icon-btn"
            onClick={() => void handleToggleFullscreen()}
          >
            {isFullscreen ? (
              <Minimize size={16} strokeWidth={1.8} />
            ) : (
              <Maximize size={16} strokeWidth={1.8} />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
