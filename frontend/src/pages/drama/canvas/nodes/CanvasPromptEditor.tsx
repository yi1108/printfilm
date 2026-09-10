/** 画布提示词：contentEditable，@asset 显示为带小图的标签 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { resolveDramaMediaUrl } from '../../../../api/drama'
import {
  deleteAdjacentEditorChip,
  detectActiveMentionTrigger,
  insertMentionChipAtRange,
  renderPromptEditorContent,
  serializePromptEditorContent,
} from '../../../../lib/dramaEpisodePromptEditor'
import {
  CanvasMentionPopover,
  filterCanvasMentionItems,
  type CanvasMentionItem,
} from './CanvasMentionPopover'

type CanvasPromptEditorProps = {
  value: string
  placeholder: string
  disabled?: boolean
  allowMention: boolean
  mentionItems: CanvasMentionItem[]
  onChange: (next: string) => void
  onSubmit: () => void
}

type MentionUi = {
  open: boolean
  query: string
  activeIndex: number
}

const EMPTY_MENTION: MentionUi = { open: false, query: '', activeIndex: 0 }

/** 把选中资产写入正文并渲染小图标签 */
function applyMentionToken(content: string, token: string) {
  const trimmed = content.replace(/\s+$/u, '')
  if (/@(?!(?:asset|duration):\d+)[^\s@]*$/.test(trimmed)) {
    return trimmed.replace(/@(?!(?:asset|duration):\d+)[^\s@]*$/, `${token} `)
  }
  return trimmed ? `${trimmed} ${token} ` : `${token} `
}

/** 可编辑提示词：插入 @ 后渲染资产小图标签 */
export function CanvasPromptEditor({
  value,
  placeholder,
  disabled = false,
  allowMention,
  mentionItems,
  onChange,
  onSubmit,
}: CanvasPromptEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const lastEmittedRef = useRef(value)
  const [mention, setMention] = useState<MentionUi>(EMPTY_MENTION)

  const byAssetId = useMemo(
    () => new Map(mentionItems.map((item) => [item.assetId, item])),
    [mentionItems],
  )

  /** 把 @asset:id 解析成 chip 数据 */
  const resolveChip = useCallback(
    (assetId: number) => {
      const item = byAssetId.get(assetId)
      if (!item) return null
      return {
        assetId,
        label: item.label,
        previewUrl: resolveDramaMediaUrl(item.mediaUrl) || null,
      }
    },
    [byAssetId],
  )

  /** 把 value 刷到编辑器 DOM */
  const paint = useCallback(
    (next: string) => {
      const editor = editorRef.current
      if (!editor) return
      renderPromptEditorContent(editor, next, resolveChip)
    },
    [resolveChip],
  )

  const paintedRef = useRef(false)
  useEffect(() => {
    if (paintedRef.current && value === lastEmittedRef.current) return
    paint(value)
    lastEmittedRef.current = value
    paintedRef.current = true
  }, [paint, value])

  /** 关闭 @ 弹层 */
  const closeMention = useCallback(() => {
    setMention(EMPTY_MENTION)
  }, [])

  /** 序列化编辑器并回写 */
  const emitContent = useCallback(() => {
    const editor = editorRef.current
    if (!editor) return ''
    const next = serializePromptEditorContent(editor)
    lastEmittedRef.current = next
    onChange(next)
    return next
  }, [onChange])

  /** 根据光标前正文刷新 @ 弹层 */
  const syncMention = useCallback(() => {
    const editor = editorRef.current
    if (!editor || disabled || !allowMention) {
      closeMention()
      return
    }
    const hit = detectActiveMentionTrigger(editor)
    if (!hit) {
      closeMention()
      return
    }
    setMention({
      open: true,
      query: hit.query,
      activeIndex: 0,
    })
  }, [allowMention, closeMention, disabled])

  /** 插入资产小图标签（优先替换光标处的 @，避免整段重绘后无法再触发） */
  const insertMention = useCallback(
    (item: CanvasMentionItem) => {
      const editor = editorRef.current
      if (!editor) return
      const token = `@asset:${item.assetId}`
      const chip = resolveChip(item.assetId) || {
        assetId: item.assetId,
        label: item.label,
        previewUrl: resolveDramaMediaUrl(item.mediaUrl) || null,
      }
      const hit = detectActiveMentionTrigger(editor)
      if (hit?.range) {
        insertMentionChipAtRange(hit.range, chip)
      } else {
        const next = applyMentionToken(serializePromptEditorContent(editor), token)
        paint(next)
        requestAnimationFrame(() => {
          editor.focus()
          const sel = window.getSelection()
          if (!sel) return
          const range = document.createRange()
          range.selectNodeContents(editor)
          range.collapse(false)
          sel.removeAllRanges()
          sel.addRange(range)
        })
      }
      const next = serializePromptEditorContent(editor)
      lastEmittedRef.current = next
      onChange(next)
      closeMention()
      requestAnimationFrame(() => {
        editor.focus()
      })
    },
    [closeMention, onChange, paint, resolveChip],
  )

  const filtered = filterCanvasMentionItems(mentionItems, mention.query)

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (
      !disabled &&
      (event.key === 'Backspace' || event.key === 'Delete') &&
      editorRef.current
    ) {
      const removed = deleteAdjacentEditorChip(
        editorRef.current,
        event.key === 'Backspace' ? 'backward' : 'forward',
      )
      if (removed) {
        event.preventDefault()
        emitContent()
        closeMention()
        return
      }
    }

    if (mention.open && filtered.length > 0) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setMention((m) => ({
          ...m,
          activeIndex: Math.min(m.activeIndex + 1, filtered.length - 1),
        }))
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setMention((m) => ({
          ...m,
          activeIndex: Math.max(m.activeIndex - 1, 0),
        }))
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        closeMention()
        return
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        const pick = filtered[mention.activeIndex]
        if (pick) insertMention(pick)
        return
      }
    }

    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit()
    }
  }

  const empty = !value.trim()

  return (
    <div className="fc-generate-input-wrap">
      <div
        ref={editorRef}
        className={`fc-generate-input fc-generate-editor nodrag nopan nowheel${empty ? ' is-empty' : ''}`}
        role="textbox"
        aria-multiline="true"
        aria-label="生成提示词"
        contentEditable={!disabled}
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={() => {
          emitContent()
          syncMention()
        }}
        onKeyUp={syncMention}
        onClick={syncMention}
        onKeyDown={(event) => {
          event.stopPropagation()
          handleKeyDown(event)
        }}
        onBlur={() => {
          emitContent()
        }}
      />
      <CanvasMentionPopover
        open={mention.open}
        query={mention.query}
        items={mentionItems}
        activeIndex={mention.activeIndex}
        onActiveIndexChange={(index) => setMention((m) => ({ ...m, activeIndex: index }))}
        onSelect={insertMention}
        onClose={closeMention}
      />
    </div>
  )
}
