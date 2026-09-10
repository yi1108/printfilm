/**
 * 漫剧运镜 / 景别词库（对齐 docs/EPISODE_RULES.md §5）
 * 供分集编辑 @ 菜单插入画面行前缀或运镜短语
 */

export type DramaCameraLexiconGroup = 'shot' | 'move'

export type DramaCameraLexiconItem = {
  id: string
  group: DramaCameraLexiconGroup
  /** 列表展示名 */
  label: string
  /** 插入到脚本的文本（用户可继续补描写） */
  insert: string
  /** 一行说明 */
  hint: string
}

/** 景别标签：写入画面行，勿标成对白 */
export const DRAMA_SHOT_SIZE_LEXICON: DramaCameraLexiconItem[] = [
  { id: 'empty', group: 'shot', label: '空镜', insert: '空镜：', hint: '环境建立，无对白无旁白' },
  { id: 'wide', group: 'shot', label: '远景', insert: '远景：', hint: '交代空间关系' },
  { id: 'full', group: 'shot', label: '全景', insert: '全景：', hint: '全身与环境同框' },
  { id: 'medium', group: 'shot', label: '中景', insert: '中景：', hint: '腰部以上，对白常用' },
  { id: 'close', group: 'shot', label: '近景', insert: '近景：', hint: '胸部以上，情绪贴近' },
  { id: 'closeup', group: 'shot', label: '特写', insert: '特写：', hint: '脸或关键道具' },
  { id: 'ecu', group: 'shot', label: '大特写', insert: '大特写：', hint: '眼、手、细节' },
  { id: 'establish', group: 'shot', label: '建立镜头', insert: '建立镜头：', hint: '开场定场景气氛' },
  { id: 'atmosphere', group: 'shot', label: '气氛镜头', insert: '气氛镜头：', hint: '光影/天气/物件烘托' },
]

/** 运镜短语：单段运动轴建议 ≤ 2 */
export const DRAMA_CAMERA_MOVE_LEXICON: DramaCameraLexiconItem[] = [
  { id: 'push', group: 'move', label: '推镜', insert: '推镜：', hint: '镜头前推靠近主体' },
  { id: 'pull', group: 'move', label: '拉镜', insert: '拉镜：', hint: '镜头后拉展开空间' },
  { id: 'pan', group: 'move', label: '摇镜', insert: '摇镜：', hint: '机位不动，水平/垂直扫视' },
  { id: 'truck', group: 'move', label: '移镜', insert: '移镜：', hint: '机位平移跟随' },
  { id: 'follow', group: 'move', label: '跟拍', insert: '跟拍：', hint: '跟随人物移动' },
  { id: 'high', group: 'move', label: '俯拍', insert: '俯拍：', hint: '高角度向下' },
  { id: 'low', group: 'move', label: '仰拍', insert: '仰拍：', hint: '低角度向上' },
  { id: 'aerial', group: 'move', label: '航拍', insert: '航拍：', hint: '大全景俯视' },
]

/** 合并词库（插入列表用） */
export const DRAMA_CAMERA_LEXICON: DramaCameraLexiconItem[] = [
  ...DRAMA_SHOT_SIZE_LEXICON,
  ...DRAMA_CAMERA_MOVE_LEXICON,
]

/** 运镜使用提示（只展示，不插入） */
export const DRAMA_CAMERA_USAGE_TIPS = [
  '公式：主体 + 动作 + 场景 +（景别/运镜）+（光影）',
  '每段运动轴 ≤ 2（推+摇可以；推+摇+升易失控）',
  '近景大旋转易崩脸，环绕留给中景以上',
  '空镜/景别必须用画面写法，禁止标成对白或旁白',
] as const

// 按关键字过滤词库（匹配 label / insert / hint）
export function filterDramaCameraLexicon(
  items: DramaCameraLexiconItem[],
  query: string,
): DramaCameraLexiconItem[] {
  const q = (query || '').trim().toLowerCase()
  if (!q) return items
  return items.filter(
    (item) =>
      item.label.toLowerCase().includes(q) ||
      item.insert.toLowerCase().includes(q) ||
      item.hint.toLowerCase().includes(q),
  )
}
