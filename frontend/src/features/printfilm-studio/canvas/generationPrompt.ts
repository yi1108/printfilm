type TextReference = { type?: string; data: { text?: unknown; label?: unknown } }

/** Connected writing can supply the prompt when the media node has no draft. */
export function connectedGenerationPrompt(draft: string, references: TextReference[]): string {
  if (draft.trim()) return draft
  const texts = references.filter(node => ['text', 'script'].includes(node.type || ''))
    .map(node => ({ label: String(node.data.label || '参考文本'), text: String(node.data.text || '').trim() }))
    .filter(node => node.text)
  return (texts.length === 1 ? texts[0].text : texts.map(node => `${node.label}：${node.text}`).join('\n\n')).slice(0, 6000)
}
