import { marketText as mt } from './translate'

export default function ContentBadges({ item }: { item: { is_featured?: boolean; is_pinned?: boolean } }) {
  if (!item.is_featured && !item.is_pinned) return null
  return <span className="pf-market-curation-badges">
    {item.is_pinned && <span className="pf-market-curation-badge is-pinned">{mt('置顶')}</span>}
    {item.is_featured && <span className="pf-market-curation-badge is-featured">{mt('精选')}</span>}
  </span>
}
