import { normalizeReferenceTokens, splitPrompt, type PromptReference } from './promptMentions'

/** Display stored image identities using current canvas URLs, never model-supplied URLs. */
export function PromptText({ value, references }: { value: string; references: PromptReference[] }) {
  return <span style={{ whiteSpace: 'pre-wrap' }}>{splitPrompt(normalizeReferenceTokens(value, references)).map((part, index) => {
    if ('text' in part) return part.text
    const ref = references.find(item => item.id === part.reference.id && item.source === part.reference.source)
    return <span key={index} className="pf-inline-reference" title={ref?.label || part.reference.label}>
      {ref?.url && ref.mediaKind === 'image' && <img src={ref.url} alt="" draggable={false} />}
      {ref?.label || part.reference.label}
    </span>
  })}</span>
}
