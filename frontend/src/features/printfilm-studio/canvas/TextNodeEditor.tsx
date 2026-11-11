import { useEffect, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import { Bold, Check, Copy, Heading1, Heading2, Heading3, Italic, List, ListOrdered, Minus, Pilcrow, X } from 'lucide-react'
import { CanvasReference } from './referenceExtension'
import { normalizeReferenceTokens, type PromptReference } from './promptMentions'
import { studioTextExtensions } from './richTextExtensions'
import type { InspectorDraft } from './NodePanels'
import './textNodeEditor.css'

export function TextNodeEditor({ draft, writable, onChange, onSave, onClose, embedded = false, references = [] }: {
  draft: InspectorDraft; writable: boolean; onChange: (draft: InspectorDraft) => void; onSave: () => void; onClose: () => void; embedded?: boolean; references?: PromptReference[]
}) {
  const dialog = useRef<HTMLElement>(null)
  const initialText = useRef(draft.text)
  const latestText = useRef(draft.text)
  const [copyStatus, setCopyStatus] = useState('')
  const referenceRef = useRef(references); referenceRef.current = references
  const referenceKey = JSON.stringify(references.map(({id,source,label,url}) => ({id,source,label,url})))
  const editor = useEditor({
    extensions: [...studioTextExtensions, CanvasReference.configure({ references: () => referenceRef.current })],
    content: normalizeReferenceTokens(draft.text, references),
    contentType: 'markdown',
    editable: writable,
    immediatelyRender: false,
    shouldRerenderOnTransaction: true,
    editorProps: { attributes: { role: 'textbox', 'aria-label': '文本正文', 'aria-multiline': 'true', spellcheck: 'false' } },
    onUpdate: ({ editor: current }) => {
      latestText.current = current.getMarkdown()
      onChange({ ...draft, text: latestText.current })
    },
  }, [referenceKey])
  useEffect(() => {
    if (embedded) return
    const previous = document.activeElement as HTMLElement | null
    dialog.current?.focus({ preventScroll: true })
    return () => { if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [embedded])
  useEffect(() => { editor?.setEditable(writable, false) }, [editor, writable])
  useEffect(() => {
    if (editor && draft.text !== latestText.current) {
      latestText.current = draft.text
      editor.commands.setContent(normalizeReferenceTokens(draft.text, referenceRef.current), { contentType: 'markdown', emitUpdate: false })
    }
  }, [draft.text, editor])
  useEffect(() => {
    if (!copyStatus) return
    const timer = window.setTimeout(() => setCopyStatus(''), 2500)
    return () => window.clearTimeout(timer)
  }, [copyStatus])
  const close = () => {
    if (writable && draft.text !== initialText.current) onSave()
    else onClose()
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(editor?.getText() || draft.text); setCopyStatus('已复制') }
    catch { setCopyStatus('复制失败，请选中正文后复制') }
  }
  const formats = [
    { label: '一级标题', Icon: Heading1, active: editor?.isActive('heading', { level: 1 }), run: () => editor?.chain().focus().toggleHeading({ level: 1 }).run() },
    { label: '二级标题', Icon: Heading2, active: editor?.isActive('heading', { level: 2 }), run: () => editor?.chain().focus().toggleHeading({ level: 2 }).run() },
    { label: '三级标题', Icon: Heading3, active: editor?.isActive('heading', { level: 3 }), run: () => editor?.chain().focus().toggleHeading({ level: 3 }).run() },
    { label: '正文', Icon: Pilcrow, active: editor?.isActive('paragraph'), run: () => editor?.chain().focus().setParagraph().run() },
    { label: '加粗', Icon: Bold, divider: true, active: editor?.isActive('bold'), run: () => editor?.chain().focus().toggleBold().run() },
    { label: '斜体', Icon: Italic, active: editor?.isActive('italic'), run: () => editor?.chain().focus().toggleItalic().run() },
    { label: '无序列表', Icon: List, divider: true, active: editor?.isActive('bulletList'), run: () => editor?.chain().focus().toggleBulletList().run() },
    { label: '有序列表', Icon: ListOrdered, active: editor?.isActive('orderedList'), run: () => editor?.chain().focus().toggleOrderedList().run() },
    { label: '分隔线', Icon: Minus, run: () => editor?.chain().focus().setHorizontalRule().run() },
  ]
  return <div className={embedded ? 'pf-text-editor-embedded' : 'pf-text-editor-backdrop'} onMouseDown={(event) => event.stopPropagation()}>
    <section ref={dialog} tabIndex={-1} role={embedded ? 'region' : 'dialog'} aria-modal={embedded ? undefined : true} aria-label="编辑文本节点" className="pf-text-editor" onKeyDown={(event) => {
      event.stopPropagation()
      if (event.nativeEvent.isComposing) return
      if (embedded) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); onSave() }; return }
      if (event.key === 'Escape') { event.preventDefault(); close(); return }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); close(); return }
      if (event.key === 'Tab') {
        const items = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),[role="textbox"]') || [])]
        const current = items.indexOf(document.activeElement as HTMLElement)
        if (current < 0 || event.shiftKey && current === 0 || !event.shiftKey && current === items.length - 1) {
          event.preventDefault(); (event.shiftKey ? items.at(-1) : items[0])?.focus()
        }
      }
    }}>
      <header className="pf-text-editor-toolbar">
        <nav aria-label="文本格式">
          {formats.map(({ label, Icon, active, run, divider }) => <span key={label} className={divider ? 'pf-text-editor-tool-group' : undefined}>
            <button type="button" aria-label={label} title={label} aria-pressed={active} disabled={!writable || !editor} onMouseDown={(event) => event.preventDefault()} onClick={run}><Icon size={19} strokeWidth={1.8} /></button>
          </span>)}
          <span className="pf-text-editor-tool-group"><button type="button" aria-label="复制正文" title="复制正文" onMouseDown={(event) => event.preventDefault()} onClick={() => void copy()}>{copyStatus === '已复制' ? <Check size={19} /> : <Copy size={19} strokeWidth={1.8} />}</button></span>
        </nav>
        <span className="pf-text-editor-status" role="status">{copyStatus || (!writable ? '只读' : '')}</span>
        {!embedded && <button type="button" className="pf-text-editor-close" aria-label="关闭文本编辑器" title={writable ? '保存并关闭（Esc）' : '关闭（Esc）'} onClick={close}><X size={23} strokeWidth={1.8} /></button>}
      </header>
      <div className="pf-text-editor-content"><EditorContent editor={editor} /></div>
    </section>
  </div>
}
