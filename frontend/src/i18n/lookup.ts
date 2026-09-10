/** 按点路径取文案，并用 {name} 做插值 */

export type TVars = Record<string, string | number>

// 从嵌套对象按 "nav.home" 取字符串
export function lookupMessage(source: unknown, path: string): string | undefined {
  const parts = path.split('.')
  let cur: unknown = source
  for (const part of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[part]
  }
  return typeof cur === 'string' ? cur : undefined
}

// 将模板中的 {key} 替换为 vars
export function interpolate(template: string, vars?: TVars): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : match,
  )
}
