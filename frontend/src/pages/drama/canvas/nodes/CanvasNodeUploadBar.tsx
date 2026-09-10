/** 选中节点顶部：本地上传 + 从全局资产库选择 + 角色音色生成/试听 */
import { useCallback, useRef, useState, type ChangeEvent, type MouseEvent } from 'react'
import { AudioLines, FolderOpen, Loader2, Upload } from 'lucide-react'
import { dramaApi } from '../../../../api/drama'
import { CharacterVoicePreviewButton } from '../../../../components/drama/CharacterVoicePreviewButton'
import { generateAndBindCharacterVoice } from '../../../../lib/characterVoiceGenerate'
import { useCanvasStore } from '../CanvasStore'
import { CANVAS_UPLOADABLE_KINDS, type CanvasNodeKind } from '../canvasTypes'
import {
  canvasKindToLibraryTypes,
  GlobalAssetPickerModal,
} from '../../GlobalAssetPickerModal'

type CanvasNodeUploadBarProps = {
  nodeId: string
  kind: CanvasNodeKind
  /** 角色节点已绑定音色名 */
  voiceLabel?: string | null
  /** 角色节点已绑定音色试听地址 */
  voiceUrl?: string | null
}

/** 渲染选中节点的上传与资产库操作条 */
export function CanvasNodeUploadBar({
  nodeId,
  kind,
  voiceLabel,
  voiceUrl,
}: CanvasNodeUploadBarProps) {
  /*
   * uploading 本地上传中
   * pickerOpen 资产库弹窗
   * voiceLoading 音色生成或拉取角色资产中
   */
  const {
    uploadNodeMedia,
    applyLibraryMediaToNode,
    syncNodeFromAsset,
    ensureNodeAsset,
    setErrorMessage,
    projectId,
  } = useCanvasStore()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [voiceLoading, setVoiceLoading] = useState(false)

  const stopFlowEvent = useCallback((event: MouseEvent) => {
    event.stopPropagation()
  }, [])

  if (!CANVAS_UPLOADABLE_KINDS.has(kind)) return null

  const isCharacter = kind === 'character'
  const hasVoice = Boolean(voiceUrl || voiceLabel)

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    if (!file.type.startsWith('image/')) {
      setErrorMessage('请选择图片文件')
      return
    }
    if (file.size > 20 * 1024 * 1024) {
      setErrorMessage('图片不能超过 20MB')
      return
    }

    setUploading(true)
    void uploadNodeMedia(nodeId, file)
      .catch((err) => setErrorMessage(err instanceof Error ? err.message : '上传失败'))
      .finally(() => setUploading(false))
  }

  // 一键 AI 生成音色并绑定到角色节点
  async function handleGenerateVoice() {
    if (voiceLoading) return
    setVoiceLoading(true)
    try {
      const assetId = await ensureNodeAsset(nodeId)
      const list = await dramaApi.listAssets(projectId)
      const asset = list.find((a) => a.id === assetId)
      if (!asset) throw new Error('角色资产不存在')
      const { character } = await generateAndBindCharacterVoice(projectId, asset)
      syncNodeFromAsset(nodeId, character)
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : '音色生成失败')
    } finally {
      setVoiceLoading(false)
    }
  }

  return (
    <>
      <div className="fc-node-toolbar nodrag nopan" onMouseDown={stopFlowEvent} onPointerDown={stopFlowEvent}>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="fc-hidden-input"
          onChange={handleFileChange}
        />
        <button
          type="button"
          className="fc-toolbar-chip"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading ? <Loader2 size={14} className="fc-spin" /> : <Upload size={14} strokeWidth={1.8} />}
          {uploading ? '上传中…' : '上传图片'}
        </button>
        <button
          type="button"
          className="fc-toolbar-chip"
          disabled={uploading}
          onClick={() => setPickerOpen(true)}
        >
          <FolderOpen size={14} strokeWidth={1.8} />
          从资产库选择
        </button>
        {isCharacter ? (
          hasVoice && voiceUrl ? (
            <CharacterVoicePreviewButton
              url={voiceUrl}
              label={voiceLabel || undefined}
              variant="chip"
              className="is-active"
              onError={setErrorMessage}
            />
          ) : (
            <button
              type="button"
              className="fc-toolbar-chip"
              disabled={uploading || voiceLoading}
              onClick={() => void handleGenerateVoice()}
              title="按角色设定 AI 生成音色"
            >
              {voiceLoading ? (
                <Loader2 size={14} className="fc-spin" />
              ) : (
                <AudioLines size={14} strokeWidth={1.8} />
              )}
              {voiceLoading ? '生成中…' : '生成音色'}
            </button>
          )
        ) : null}
      </div>

      <GlobalAssetPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        projectId={projectId}
        defaultTab="all"
        allowedTypes={canvasKindToLibraryTypes(kind)}
        title="从资产库选择"
        confirmLabel="确认使用"
        onPick={async (source) => {
          await applyLibraryMediaToNode(nodeId, source)
        }}
      />
    </>
  )
}
