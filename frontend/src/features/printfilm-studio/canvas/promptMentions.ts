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

export function appendPromptReferences(value: string, references: PromptReference[]) {
  const included = new Set(splitPrompt(value).flatMap(part => 'reference' in part ? [`${part.reference.source}:${part.reference.id}`] : []))
  const tokens = []
  for (const reference of references) {
    const key = `${reference.source}:${reference.id}`
    if (included.has(key)) continue
    included.add(key)
    tokens.push(mentionToken(reference))
  }
  return tokens.length ? `${value}\n参考素材：${tokens.join('、')}` : value
}

/** Bind only unambiguous material names, visiting each matched asset once per paste. */
export function bindNamedPromptReferences<T extends PromptReference & { identity?: string }>(
  value: string, candidates: T[], bind: (item: T) => PromptReference | undefined,
) {
  const names = new Map<string, Map<string, T>>()
  for (const item of candidates) {
    const label = item.label.trim().toLowerCase()
    const stem = label.replace(/\.(?:png|jpe?g|webp|gif|bmp|avif|mp4|mov|webm|wav|mp3|m4a|aac|ogg|flac)$/i, '')
    for (const name of new Set([label, stem])) {
      if (name.length < 2) continue
      const matches = names.get(name) ?? new Map<string, T>()
      const identity = item.identity ?? `${item.source}:${item.id}`
      if (!matches.has(identity)) matches.set(identity, item)
      names.set(name, matches)
    }
  }
  if (!names.size) return value
  const alternatives = [...names.keys()].sort((a, b) => b.length - a.length).map(name => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const pattern = new RegExp(`(?<![A-Za-z0-9_])@?(${alternatives})(?![A-Za-z0-9_]|\\.[A-Za-z0-9])`, 'gi')
  const bound = new Map<string, PromptReference | undefined>()
  for (const part of splitPrompt(value)) {
    if ('token' in part) continue
    for (const [, label] of part.text.matchAll(pattern)) {
      const matches = names.get(label.toLowerCase())
      if (matches?.size !== 1) continue
      const [identity, item] = matches.entries().next().value!
      if (!bound.has(identity)) bound.set(identity, bind(item))
    }
  }
  return appendPromptReferences(value, [...bound.values()].filter(reference => reference !== undefined))
}

export function bindUploadedImageMentions(value: string, images: readonly { nodeId: string; assetId?: string }[]) {
  let inReferenceList = false
  return splitPrompt(value).map((part) => {
    if ('text' in part) {
      if (part.text.includes('\n')) inReferenceList = part.text.slice(part.text.lastIndexOf('\n') + 1) === '参考素材：'
      return part.text
    }
    const { source, id, label } = part.reference
    const index = images.findIndex(image => (source === 'node' ? image.nodeId : image.assetId) === id)
    if (index < 0) return `@${label}`
    const marker = `@图片${index + 1}`
    return inReferenceList ? `${label}（${marker}）` : marker
  }).join('')
}

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
