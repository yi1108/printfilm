/** Strip internal Seedream lock wrappers from prompts shown in UI. */
export function scenePromptForDisplay(raw: string | null | undefined): string {
  if (!raw) return ''
  const scene = raw.match(/【场景】\s*([\s\S]+?)(?=\n【|$)/)
  if (scene?.[1]) {
    return scene[1].replace(/^[，,。\s]+|[，,。\s]+$/g, '').trim()
  }
  const boilerplate = [
    '同一画风',
    '全片必须保持',
    '凡出现人物',
    '禁止写实',
    '禁止换脸',
    '禁止镜头间切换',
    '必须严格沿用',
    '画面干净无文字',
  ]
  return raw
    .split(/[，,\n]/)
    .map((p) => p.trim())
    .filter((p) => {
      if (!p) return false
      if (/^【(?:风格锁定|人物锁定|约束)】/.test(p)) return false
      if (p.startsWith('人物设定') || p.startsWith('角色设定')) return false
      if (boilerplate.some((b) => p.includes(b) || p.startsWith(b))) return false
      return true
    })
    .join('，')
    .replace(/【(?:风格锁定|人物锁定|约束|场景)】/g, '')
    .replace(/[，,]{2,}/g, '，')
    .replace(/^[，,。；;\s]+|[，,。；;\s]+$/g, '')
    .trim()
}
