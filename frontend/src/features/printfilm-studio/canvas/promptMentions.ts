export type PromptReference = { id: string; source: 'node' | 'asset'; label: string; url?: string; mediaKind?: string }
export function normalizeReferenceTokens(value: string, references: PromptReference[] = []) {
  const normalized = value.replace(/@?\[([^\]]*)\]\((node|asset):([^)]*)\)/g, (raw, label, source, id) => {
    try { return mentionToken({ label: decodeURIComponent(label), source, id: decodeURIComponent(id) }) } catch { return raw }
  })
  return splitPrompt(normalized).map(part => {
    if ('token' in part) return part.token
    let text = part.text
    for (const ref of references) {
      if (ref.label && encodeURIComponent(ref.label) !== ref.label) text = text.split(`@${encodeURIComponent(ref.label)}`).join(mentionToken(ref))
    }
    return text
  }).join('')
}
export function mentionToken(item: PromptReference) { return `@[${encodeURIComponent(item.label)}](${item.source}:${encodeURIComponent(item.id)})` }
export function splitPrompt(value: string): ({ text: string } | { token: string; reference: PromptReference })[] {
  const parts: ({ text: string } | { token: string; reference: PromptReference })[] = []
  const pattern = /@\[([^\]]*)\]\((node|asset):([^)]*)\)/g
  let last = 0
  for (const match of value.matchAll(pattern)) {
    if (match.index! > last) parts.push({ text: value.slice(last, match.index) })
    try { parts.push({ token: match[0], reference: { label: decodeURIComponent(match[1]), source: match[2] as 'node' | 'asset', id: decodeURIComponent(match[3]) } }) } catch { parts.push({ text: match[0] }) }
    last = match.index! + match[0].length
  }
  if (last < value.length) parts.push({ text: value.slice(last) })
  return parts
}
export function plainPrompt(value: string) { return splitPrompt(value).map((part) => 'text' in part ? part.text : `@${part.reference.label}`).join('') }

/** Keep stable reference IDs in storage, never serialize thumbnail URLs into the prompt. */
export function readPromptDom(root: Node): string {
  if (root.nodeType === 3) return root.textContent || ''
  if (root instanceof HTMLElement) {
    if (root.dataset.promptToken) return root.dataset.promptToken
    if (root.tagName === 'BR') return '\n'
  }
  return Array.from(root.childNodes).map((node, index) => {
    const text = readPromptDom(node)
    return node instanceof HTMLElement && ['DIV', 'P'].includes(node.tagName) && index > 0 ? `\n${text}` : text
  }).join('')
}

export function mentionQuery(value: string, caret: number): string | null {
  const before = value.slice(0, caret)
  const at = before.lastIndexOf('@')
  if (at < 0) return null
  const query = before.slice(at + 1)
  if (/\s/.test(query)) return null
  return query
}


export function promptCaret(el: HTMLElement) {
  const selection = window.getSelection()
  if (!selection?.rangeCount || !selection.anchorNode || !el.contains(selection.anchorNode)) return readPromptDom(el).length
  const range = selection.getRangeAt(0).cloneRange(); range.selectNodeContents(el); range.setEnd(selection.anchorNode, selection.anchorOffset)
  return readPromptDom(range.cloneContents()).length
}
