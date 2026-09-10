import { Clapperboard, Image, Images, Play, ShoppingBag, Sparkles, Video } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Messages } from '../i18n'

export type ToolId = 't2i' | 'i2i' | 'i2p' | 't2v' | 'v2v' | 'ecom'

export type ToolField = {
  key: string
  label: string
  kind: 'textarea' | 'upload' | 'chips'
  options?: string[]
  multiple?: boolean
  accept?: string
  placeholder?: string
}

export type ToolDef = {
  id: ToolId
  title: string
  desc: string
  soon: boolean
  icon: LucideIcon
  /** 左侧控件区文案提示 */
  panelHint: string
  fields: ToolField[]
  cta: string
}

export const TOOL_DEFS: ToolDef[] = [
  {
    id: 't2i',
    title: '文生图',
    desc: '用文字描述生成高质量画面',
    soon: false,
    icon: Image,
    panelHint: '用文字描述画面，选择画幅后即可生成。',
    fields: [
      { key: 'prompt', label: '提示词', kind: 'textarea', placeholder: '描述主体、场景、光线与风格…' },
      { key: 'negative', label: '反向提示词', kind: 'textarea', placeholder: '不想出现的内容，如文字、水印…' },
      { key: 'ratio', label: '画幅', kind: 'chips', options: ['1:1', '16:9', '9:16'] },
    ],
    cta: '生成',
  },
  {
    id: 'i2i',
    title: '图生图',
    desc: '上传参考图，生成风格一致的变体',
    soon: false,
    icon: Sparkles,
    panelHint: '上传参考图，描述希望保留或改变的部分。',
    fields: [
      { key: 'ref', label: '参考图', kind: 'upload', accept: 'image/*' },
      { key: 'prompt', label: '提示词', kind: 'textarea', placeholder: '保持主体，改为电影感夜景…' },
      { key: 'strength', label: '相似度', kind: 'chips', options: ['低', '中', '高'] },
    ],
    cta: '生成',
  },
  {
    id: 'i2p',
    title: '图生产品',
    desc: '一键生成白底图与场景商品图',
    soon: false,
    icon: ShoppingBag,
    panelHint: '上传商品图，选择白底、场景或详情长图。',
    fields: [
      { key: 'product', label: '商品图', kind: 'upload', accept: 'image/*' },
      { key: 'mode', label: '输出类型', kind: 'chips', options: ['白底图', '场景图', '详情长图'] },
      { key: 'prompt', label: '补充描述（可选）', kind: 'textarea', placeholder: '材质、摆放、使用场景…' },
    ],
    cta: '生成商品图',
  },
  {
    id: 't2v',
    title: '文生视频',
    desc: '从脚本生成短视频片段',
    soon: false,
    icon: Play,
    panelHint: '填写脚本后先出静帧，再生成短视频（约 1–3 分钟）。',
    fields: [
      { key: 'script', label: '视频脚本', kind: 'textarea', placeholder: '描述镜头运动、主体动作与氛围…' },
      { key: 'duration', label: '时长', kind: 'chips', options: ['5s', '10s', '15s'] },
      { key: 'ratio', label: '画幅', kind: 'chips', options: ['16:9', '9:16'] },
    ],
    cta: '生成视频',
  },
  {
    id: 'v2v',
    title: '视频生视频',
    desc: '对已有视频做风格与运动变换',
    soon: false,
    icon: Clapperboard,
    panelHint: '上传源视频或首帧图，描述风格与运动强度。',
    fields: [
      {
        key: 'source',
        label: '源视频 / 首帧',
        kind: 'upload',
        accept: 'video/mp4,video/quicktime,video/webm,image/*',
      },
      { key: 'prompt', label: '变换描述', kind: 'textarea', placeholder: '改为赛博朋克夜景，镜头缓缓推进…' },
      { key: 'motion', label: '运动强度', kind: 'chips', options: ['弱', '中', '强'] },
    ],
    cta: '开始变换',
  },
  {
    id: 'ecom',
    title: '电商工具',
    desc: '主图拼接、详情排版等小工具合集',
    soon: false,
    icon: Images,
    panelHint: '拼接至少 2 张图；卖点海报上传 1 张商品图即可生成。',
    fields: [
      { key: 'pack', label: '工具包', kind: 'chips', options: ['主图拼接', '详情排版', '卖点海报'] },
      { key: 'images', label: '图片', kind: 'upload', multiple: true, accept: 'image/*' },
      { key: 'prompt', label: '卖点描述（海报可选）', kind: 'textarea', placeholder: '突出材质与使用场景…' },
    ],
    cta: '开始制作',
  },
]

// 按 id 查找工具定义
export function getToolDef(id: string | undefined): ToolDef | undefined {
  return TOOL_DEFS.find((t) => t.id === id)
}

export const PRODUCT_ICONS = { drama: Clapperboard, kepu: Video }

// 芯片字段的默认选中项（取 options 第一项；值为中文枚举，给后端）
export function defaultToolChips(tool: ToolDef): Record<string, string> {
  const chips: Record<string, string> = {}
  for (const field of tool.fields) {
    if (field.kind === 'chips' && field.options?.[0]) chips[field.key] = field.options[0]
  }
  return chips
}

// 用当前语言覆盖工具标题、说明与字段文案（options 值保持中文给 API）
export function localizeToolDef(tool: ToolDef, m: Messages): ToolDef {
  const pack = m.tools.items[tool.id]
  return {
    ...tool,
    title: pack.title,
    desc: pack.desc,
    panelHint: pack.panelHint,
    cta: pack.cta,
    fields: tool.fields.map((field) => {
      const f = pack.fields[field.key as keyof typeof pack.fields] as
        | { label?: string; placeholder?: string }
        | undefined
      return {
        ...field,
        label: f?.label || field.label,
        placeholder: f?.placeholder || field.placeholder,
      }
    }),
  }
}

export function localizeToolDefs(m: Messages): ToolDef[] {
  return TOOL_DEFS.map((tool) => localizeToolDef(tool, m))
}

// 芯片展示文案；未知值原样返回
export function chipDisplayLabel(value: string, m: Messages): string {
  const chips = m.tools.chips as Record<string, string>
  return chips[value] || value
}
