import { useEffect, useMemo, useState } from 'react'
import { request } from './api'
import { marketText as mt } from './translate'
import { useMarketplaceLocale } from './useMarketplaceLocale'
export type Category = { code: string; name_zh: string; name_en: string; label: string; enabled: boolean }
export function useCategories() {
  const locale = useMarketplaceLocale()
  const [items, setItems] = useState<Category[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    request<{ items: Category[] }>('/categories').then(value => { if (active) { setItems(value.items); setError('') } })
      .catch(e => { if (active) setError(mt('分类加载失败：{0}，请刷新重试。', [e.message])) })
    return () => { active = false }
  }, [locale])
  const names = useMemo(() => items.map(item => item.code), [items])
  const label = (code: string, original?: { category?: string; category_labels?: { zh: string; en: string } } | null) => {
    const item = items.find(item => item.code === code)
    return item ? (locale === 'en' ? item.name_en || item.name_zh : item.name_zh)
      : original?.category_labels?.[locale] || original?.category || code
  }
  return { items, names, label, error }
}
