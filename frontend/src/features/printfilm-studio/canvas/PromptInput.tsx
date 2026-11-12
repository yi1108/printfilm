import { useLayoutEffect, useRef, type Ref } from 'react'
import { promptCaret, readPromptDom, splitPrompt, type PromptReference } from './promptMentions'

type Props = { readOnly?: boolean; value: string; onChange: (value: string, caret: number) => void; references: PromptReference[]; placeholder?: string; label: string; className?: string; inputRef?: Ref<HTMLDivElement>; onCaret?: (value: string, caret: number) => void; onFocus?: () => void; onBlur?: () => void }
export function restorePromptCaret(root: HTMLElement, offset: number) {
  const range = document.createRange(), selection = window.getSelection()
  let remaining = offset, placed = false
  for (const node of Array.from(root.childNodes)) {
    const length = readPromptDom(node).length
    if (remaining <= length) {
      if (node.nodeType === 3) range.setStart(node, Math.min(remaining, node.textContent?.length || 0))
      else if (remaining === 0) range.setStartBefore(node)
      else range.setStartAfter(node)
      placed = true; break
    }
    remaining -= length
  }
  if (!placed) { range.selectNodeContents(root); range.collapse(false) }
  range.collapse(true); selection?.removeAllRanges(); selection?.addRange(range)
}
export function PromptInput({ value, onChange, references, placeholder, label, className = '', inputRef, onCaret, onFocus, onBlur, readOnly = false }: Props) {
  const localRef = useRef<HTMLDivElement | null>(null), composing = useRef(false)
  useLayoutEffect(() => {
    const el = localRef.current
    if (!el || composing.current) return
    const referenceVersion = JSON.stringify(references.map(item => [item.id,item.source,item.url,item.label,item.mediaKind]))
    const current = readPromptDom(el)
    // Leave the live DOM alone while typing (especially Chinese IME).
    if (current === value && el.dataset.rendered === value && el.dataset.references === referenceVersion) return
    const focused = document.activeElement === el, caret = focused ? promptCaret(el) : 0
    el.replaceChildren()
    for (const part of splitPrompt(value)) {
      if ('text' in part) { el.append(document.createTextNode(part.text)); continue }
      const ref = references.find((item) => item.id === part.reference.id && item.source === part.reference.source) || part.reference
      const chip = document.createElement('span'); chip.className = 'pf-inline-reference'; chip.contentEditable = 'false'; chip.dataset.promptToken = part.token; chip.title = ref.label
      if (ref.url && ref.mediaKind !== 'audio' && ref.mediaKind !== 'text') {
        const image = document.createElement(ref.mediaKind === 'video' ? 'video' : 'img'); image.setAttribute('src', ref.url); image.setAttribute('aria-hidden', 'true'); image.setAttribute('draggable', 'false'); if (ref.mediaKind === 'video') { (image as HTMLVideoElement).muted = true; (image as HTMLVideoElement).preload = 'metadata' }; chip.append(image)
      }
      chip.append(document.createTextNode(ref.label)); el.append(chip)
    }
    el.dataset.rendered = value; el.dataset.references = referenceVersion
    if (focused) restorePromptCaret(el, Math.min(caret, value.length))
  }, [value, references])
  const publish = (el: HTMLDivElement) => { if (readOnly) return; const text = readPromptDom(el); el.dataset.rendered = text; onChange(text, promptCaret(el)) }
  return <div ref={(el) => { localRef.current = el; if (typeof inputRef === 'function') inputRef(el); else if (inputRef) inputRef.current = el }} contentEditable={!readOnly} aria-readonly={readOnly} suppressContentEditableWarning role="textbox" aria-multiline="true" aria-label={label} data-placeholder={placeholder} className={`pf-prompt-editable nodrag nopan nowheel ${className}`} onInput={(event) => { if (!composing.current) publish(event.currentTarget) }} onCompositionStart={() => { composing.current = true }} onCompositionEnd={(event) => { composing.current = false; publish(event.currentTarget) }} onFocus={onFocus} onBlur={onBlur} onClick={(event) => onCaret?.(readPromptDom(event.currentTarget), promptCaret(event.currentTarget))} onKeyUp={(event) => { if (!composing.current && event.key !== 'Escape') onCaret?.(readPromptDom(event.currentTarget), promptCaret(event.currentTarget)) }} onPaste={(event) => { event.preventDefault(); if (readOnly) return; const text = event.clipboardData.getData('text/plain'), selection = window.getSelection(); if (!selection?.rangeCount) return; const range = selection.getRangeAt(0); range.deleteContents(); const node = document.createTextNode(text); range.insertNode(node); range.setStartAfter(node); range.collapse(true); selection.removeAllRanges(); selection.addRange(range); publish(event.currentTarget) }} />
}
