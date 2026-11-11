import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { normalizeReferenceTokens, type PromptReference } from '../canvas/promptMentions'

// Raw HTML is never executed; URLs retain the renderer's safe protocol filter.
export function MessageContent({ text, references = [] }: { text: string; references?: PromptReference[] }) {
  return <div className="pf-message-content"><ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={url => /^(node|asset):/.test(url) ? url : defaultUrlTransform(url)} components={{
    table: ({ children }) => <div className="pf-message-table" tabIndex={0} role="region" aria-label="消息表格"><table>{children}</table></div>,
    pre: ({ children }) => <pre tabIndex={0}>{children}</pre>,
    a: ({ href, children }) => {
      const match = /^(node|asset):(.*)$/.exec(href || '')
      if (match) {
        let id = match[2], label = String(children)
        try { id = decodeURIComponent(id); label = decodeURIComponent(label) } catch { /* Preserve malformed legacy labels. */ }
        const ref = references.find(item => item.id === id && item.source === match[1])
        return <span className="pf-canvas-reference">{ref?.url && ref.mediaKind === 'image' && <img src={ref.url} alt={ref.label} loading="lazy" />}{ref?.label || label}</span>
      }
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    },
    img: ({ alt }) => <span>{alt || '图片'}</span>,
  }}>{normalizeReferenceTokens(text, references)}</ReactMarkdown></div>
}
