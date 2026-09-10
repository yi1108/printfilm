/** 画布节点类型与选择器选项定义 */
import type { LucideIcon } from 'lucide-react'
import {
  AudioLines,
  Image as ImageIcon,
  Landmark,
  PlaySquare,
  Text,
  UserRound,
} from 'lucide-react'

export type CanvasNodeKind = 'character' | 'scene' | 'video' | 'image' | 'text' | 'audio'

export type CanvasNodeOption = {
  id: CanvasNodeKind
  label: string
  icon: LucideIcon
}

export type CanvasAssetNodeData = {
  kind: CanvasNodeKind
  label: string
  assetId?: number
  mediaUrl?: string | null
  textContent?: string
  generating?: boolean
  /** 视频节点 Seedance 生成参数 */
  videoOptions?: Record<string, unknown>
  [key: string]: unknown
}

/** 支持本地图片上传的节点类型 */
export const CANVAS_UPLOADABLE_KINDS = new Set<CanvasNodeKind>([
  'character',
  'scene',
  'image',
  'video',
])

/** 支持提示词 + AI 生成的节点类型 */
export const CANVAS_GENERATABLE_KINDS = new Set<CanvasNodeKind>([
  'character',
  'scene',
  'image',
  'video',
])

/** 节点类型对应的 Drama asset_type */
export function canvasKindToAssetType(kind: CanvasNodeKind): string {
  if (kind === 'video') return 'video'
  if (kind === 'audio') return 'audio'
  if (kind === 'text') return 'text'
  return 'image'
}

/** 空画布居中快速新建选项（顺序与设计稿一致） */
export const CANVAS_NODE_OPTIONS: CanvasNodeOption[] = [
  { id: 'character', label: '角色', icon: UserRound },
  { id: 'scene', label: '场景', icon: Landmark },
  { id: 'video', label: '视频', icon: PlaySquare },
  { id: 'image', label: '图片', icon: ImageIcon },
  { id: 'text', label: '文本', icon: Text },
  { id: 'audio', label: '音频', icon: AudioLines },
]

/** 左侧添加面板选项 */
export const ADD_NODE_OPTIONS: CanvasNodeOption[] = [
  { id: 'character', label: '角色', icon: UserRound },
  { id: 'scene', label: '场景', icon: Landmark },
  { id: 'text', label: '文本', icon: Text },
  { id: 'image', label: '图片', icon: ImageIcon },
  { id: 'video', label: '视频', icon: PlaySquare },
  { id: 'audio', label: '音频', icon: AudioLines },
]

export const CANVAS_NODE_OPTION_BY_KIND = Object.fromEntries(
  CANVAS_NODE_OPTIONS.map((option) => [option.id, option]),
) as Record<CanvasNodeKind, CanvasNodeOption>

/** 各类型默认展示名 */
export const CANVAS_NODE_DEFAULT_LABEL: Record<CanvasNodeKind, string> = {
  character: '新角色',
  scene: '新场景',
  video: '新视频',
  image: '新图片',
  text: '文本',
  audio: '新音频',
}

/** 节点卡片尺寸（宽 × 高，用于落点居中） */
export const CANVAS_NODE_SIZE: Record<CanvasNodeKind, { width: number; height: number }> = {
  character: { width: 200, height: 280 },
  scene: { width: 200, height: 280 },
  video: { width: 160, height: 240 },
  image: { width: 160, height: 240 },
  text: { width: 280, height: 140 },
  audio: { width: 200, height: 100 },
}

/** 网格吸附步长 */
export const CANVAS_SNAP_GRID: [number, number] = [20, 20]

/** 自动保存防抖毫秒 */
export const CANVAS_AUTO_SAVE_MS = 2000

/** 历史栈最大深度 */
export const MAX_CANVAS_HISTORY = 50
