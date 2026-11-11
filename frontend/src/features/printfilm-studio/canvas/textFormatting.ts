export type TextFormat = 'bold' | 'italic' | 'heading' | 'heading1' | 'heading3' | 'paragraph' | 'divider' | 'list' | 'ordered' | 'quote' | 'code'

/** Transform just the selection; the editor restores its caret without losing focus. */
export function formatStudioText(text: string, start: number, end: number, format: TextFormat) {
  start = Math.max(0, Math.min(start, text.length))
  end = Math.max(start, Math.min(end, text.length))
  if (format === 'bold' || format === 'italic' || format === 'code') {
    const marker = format === 'bold' ? '**' : format === 'italic' ? '*' : '`'
    const selected = text.slice(start, end) || (format === 'code' ? '代码' : '文字')
    // A second click on the same selection toggles its formatting off.
    if (start >= marker.length && text.slice(start - marker.length, start) === marker && text.slice(end, end + marker.length) === marker) {
      return { text: text.slice(0, start - marker.length) + selected + text.slice(end + marker.length), start: start - marker.length, end: end - marker.length }
    }
    return { text: text.slice(0, start) + marker + selected + marker + text.slice(end), start: start + marker.length, end: start + marker.length + selected.length }
  }
  const lineStart = start === 0 ? 0 : text.lastIndexOf('\n', start - 1) + 1
  const last = end > start && text[end - 1] === '\n' ? end - 1 : end
  const next = text.indexOf('\n', last)
  const lineEnd = next < 0 ? text.length : next
  if (format === 'divider') return { text: text.slice(0, lineEnd) + '\n\n---\n' + text.slice(lineEnd), start: lineEnd + 6, end: lineEnd + 6 }
  if (format === 'paragraph') { const value = text.slice(lineStart, lineEnd).split('\n').map((line) => line.replace(/^(#{1,6} |[-*>] |\d+\. )/, '')).join('\n'); return { text: text.slice(0, lineStart) + value + text.slice(lineEnd), start: lineStart, end: lineStart + value.length } }
  const prefix = (index: number) => format === 'heading1' ? '# ' : format === 'heading3' ? '### ' : format === 'heading' ? '## ' : format === 'list' ? '- ' : format === 'ordered' ? `${index + 1}. ` : '> '
  const lines = text.slice(lineStart, lineEnd).split('\n')
  const isFormatted = lines.every((line, index) => line.startsWith(prefix(index)))
  const replacement = lines.map((line, index) => isFormatted ? line.slice(prefix(index).length) : prefix(index) + line).join('\n')
  return { text: text.slice(0, lineStart) + replacement + text.slice(lineEnd), start: lineStart, end: lineStart + replacement.length }
}
