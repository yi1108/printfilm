/** 画布资产自定义节点：类型图标 + 媒体卡片 + 选中工具栏 */
import { memo, useCallback, useState, type ChangeEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { Handle, NodeToolbar, Position, type Node, type NodeProps } from '@xyflow/react'
import { AudioLines, Image as ImageIcon, Landmark, Loader2, Maximize2, Play, UserRound } from 'lucide-react'
import { resolveDramaMediaUrl } from '../../../api/drama'
import { isAudioUrl, isPlayableVideoUrl } from '../../../lib/canvasNodeMedia'
import { useCanvasStore } from './CanvasStore'
import {
  CANVAS_GENERATABLE_KINDS,
  CANVAS_NODE_OPTION_BY_KIND,
  CANVAS_UPLOADABLE_KINDS,
  type CanvasAssetNodeData,
} from './canvasTypes'
import { CanvasNodeGeneratePanel } from './nodes/CanvasNodeGeneratePanel'
import { CanvasNodePreviewModal } from './CanvasNodePreviewModal'
import { CanvasNodeUploadBar } from './nodes/CanvasNodeUploadBar'

/** 画布视频缩略：仅展示封面，不拦截单击（单击要选中并显示提示词面板） */
function CanvasAssetVideoPreview({ src }: { src: string }) {
  return (
    <div className="fc-asset-video">
      <video className="fc-asset-media" src={src} muted playsInline preload="metadata" />
      <span className="fc-asset-video-play" aria-hidden>
        <Play size={22} strokeWidth={2.2} fill="currentColor" />
      </span>
    </div>
  )
}

/** 按类型返回占位图标 */
function PlaceholderIcon({ kind }: { kind: CanvasAssetNodeData['kind'] }) {
  const className = 'fc-placeholder-icon'
  if (kind === 'character') return <UserRound className={className} size={40} strokeWidth={1.4} />
  if (kind === 'scene') return <Landmark className={className} size={40} strokeWidth={1.4} />
  if (kind === 'video') return <Play className={className} size={40} strokeWidth={1.4} />
  if (kind === 'audio') return <AudioLines className={className} size={32} strokeWidth={1.4} />
  if (kind === 'text') return null
  return <ImageIcon className={className} size={40} strokeWidth={1.4} />
}

/** 渲染单个画布资产节点 */
function CanvasAssetNodeComponent({ id, data, selected }: NodeProps<Node<CanvasAssetNodeData>>) {
  const { updateNodeTextContent, renameNode } = useCanvasStore()
  const option = CANVAS_NODE_OPTION_BY_KIND[data.kind]
  const Icon = option.icon
  const isText = data.kind === 'text'
  const mediaSrc = resolveDramaMediaUrl(data.mediaUrl)
  const showUpload = selected && CANVAS_UPLOADABLE_KINDS.has(data.kind)
  const showGenerate = selected && CANVAS_GENERATABLE_KINDS.has(data.kind)
  const voiceLabel = typeof data.voiceLabel === 'string' ? data.voiceLabel : ''
  const voiceUrl = typeof data.voiceUrl === 'string' ? data.voiceUrl : ''
  const displayName =
    data.kind === 'character'
      ? typeof data.characterName === 'string' && data.characterName
        ? data.characterName
        : data.label || option.label
      : data.label || option.label
  const footerLabel =
    data.kind === 'character'
      ? voiceLabel
        ? `基础形象 · ${voiceLabel}`
        : '基础形象'
      : data.kind === 'scene'
        ? displayName
        : null

  // renaming 是否正在编辑节点名称
  // draftName 编辑中的名称草稿
  // previewOpen 是否打开大屏预览
  const [renaming, setRenaming] = useState(false)
  const [draftName, setDraftName] = useState(displayName)
  const [previewOpen, setPreviewOpen] = useState(false)
  const audioSrc = resolveDramaMediaUrl(voiceUrl || (data.kind === 'audio' ? mediaSrc : ''))
  const textContent = typeof data.textContent === 'string' ? data.textContent : ''
  const canPreview = Boolean(mediaSrc || audioSrc || textContent.trim())

  const handleTextChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      updateNodeTextContent(id, event.target.value)
    },
    [id, updateNodeTextContent],
  )

  /** 进入重命名 */
  const startRename = (event: MouseEvent) => {
    event.stopPropagation()
    event.preventDefault()
    setDraftName(displayName)
    setRenaming(true)
  }

  /** 提交重命名 */
  const commitRename = () => {
    setRenaming(false)
    const next = draftName.trim()
    if (!next || next === displayName) return
    void renameNode(id, next)
  }

  const handleRenameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      commitRename()
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      setRenaming(false)
      setDraftName(displayName)
    }
  }

  /** 双击卡片：放大预览（单击留给选中 / 提示词面板） */
  const handleCardDoubleClick = (event: MouseEvent) => {
    const target = event.target as HTMLElement
    if (target.closest('textarea, input, button, a')) return
    if (!canPreview) return
    event.preventDefault()
    setPreviewOpen(true)
  }

  /** 角标放大：不冒泡，避免抢走节点选中 */
  const handleExpandClick = (event: MouseEvent) => {
    event.stopPropagation()
    event.preventDefault()
    if (!canPreview) return
    setPreviewOpen(true)
  }

  return (
    <div className={`fc-asset-node${selected ? ' is-selected' : ''}${data.generating ? ' is-generating' : ''}`}>
      {showUpload ? (
        <NodeToolbar nodeId={id} position={Position.Top} align="center" offset={10}>
          <CanvasNodeUploadBar
            nodeId={id}
            kind={data.kind}
            voiceLabel={data.kind === 'character' ? voiceLabel || null : null}
            voiceUrl={data.kind === 'character' ? voiceUrl || null : null}
          />
        </NodeToolbar>
      ) : null}

      <div className="fc-asset-node-header">
        <Icon size={14} strokeWidth={1.8} />
        {renaming ? (
          <input
            className="fc-node-rename nodrag nopan nowheel"
            value={draftName}
            autoFocus
            onChange={(e) => setDraftName(e.target.value)}
            onBlur={commitRename}
            onKeyDown={handleRenameKeyDown}
            onMouseDown={(e) => e.stopPropagation()}
            aria-label="节点名称"
          />
        ) : (
          <button
            type="button"
            className="fc-node-title nodrag nopan"
            title="双击重命名"
            onDoubleClick={startRename}
          >
            {displayName}
          </button>
        )}
      </div>

      <div
        className={`fc-asset-card${canPreview ? ' is-previewable' : ''}`}
        title={canPreview ? '双击放大预览' : undefined}
        onDoubleClick={handleCardDoubleClick}
      >
        <div className={`fc-asset-body is-${data.kind}`}>
          {isText ? (
            selected ? (
              <textarea
                className="fc-text-editor nodrag nowheel"
                value={data.textContent || ''}
                onChange={handleTextChange}
                placeholder="输入文本…"
                rows={4}
              />
            ) : (
              <span>{data.textContent || data.label || '文本'}</span>
            )
          ) : data.generating ? (
            <div className="fc-generating">
              <Loader2 size={28} className="fc-spin" />
              <span>生成中…</span>
            </div>
          ) : mediaSrc && data.kind === 'video' && isPlayableVideoUrl(mediaSrc) ? (
            <CanvasAssetVideoPreview src={mediaSrc} />
          ) : mediaSrc && (data.kind === 'audio' || isAudioUrl(mediaSrc)) ? (
            <div className="fc-asset-audio-thumb">
              <AudioLines size={28} strokeWidth={1.6} />
              <span className="fc-asset-video-play" aria-hidden>
                <Play size={18} strokeWidth={2.2} fill="currentColor" />
              </span>
            </div>
          ) : mediaSrc ? (
            <img className="fc-asset-media" src={mediaSrc} alt={displayName} draggable={false} />
          ) : (
            <PlaceholderIcon kind={data.kind} />
          )}
          {canPreview ? (
            <button
              type="button"
              className="fc-asset-expand nodrag nopan nowheel"
              title="放大预览"
              aria-label={`放大预览 ${displayName}`}
              onClick={handleExpandClick}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <Maximize2 size={14} strokeWidth={2.2} />
            </button>
          ) : null}
        </div>
        {footerLabel ? <div className="fc-asset-footer">{footerLabel}</div> : null}
      </div>

      {showGenerate ? (
        <NodeToolbar
          nodeId={id}
          className="nodrag nopan nowheel"
          position={Position.Bottom}
          align="center"
          offset={14}
          isVisible={selected}
        >
          <CanvasNodeGeneratePanel
            nodeId={id}
            kind={data.kind}
            generating={Boolean(data.generating)}
            defaultPrompt={typeof data.promptHint === 'string' ? data.promptHint : ''}
            label={data.label || ''}
            hasMedia={Boolean(mediaSrc)}
            videoOptions={data.videoOptions}
          />
        </NodeToolbar>
      ) : null}

      <Handle className="fc-handle" type="target" position={Position.Left} />
      <Handle className="fc-handle" type="source" position={Position.Right} />
      {previewOpen && canPreview ? (
        <CanvasNodePreviewModal
          payload={{
            kind: data.kind,
            title: displayName,
            mediaUrl: mediaSrc || null,
            voiceUrl: audioSrc || null,
            textContent,
          }}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}
    </div>
  )
}

export const CanvasAssetNode = memo(CanvasAssetNodeComponent)
