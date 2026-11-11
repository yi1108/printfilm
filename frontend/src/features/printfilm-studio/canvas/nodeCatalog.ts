/** 对照 Toonflow-app 节点菜单与 packages/nodes 类型。 */
export type NodeCatalogItem = {
  id: string
  label: string
  type?: string
  action?: 'upload' | 'assets' | 'history'
  children?: NodeCatalogItem[]
  hint?: string
  editor?: 'edit' | 'crop' | 'video' | 'reference' | 'audio' | 'inpaint' | 'outpaint' | 'compose'
}

/** 与 Toonflow anonymousData / resolveNodeMenu 默认顺序一致。 */
export const FULL_NODE_CATALOG: NodeCatalogItem[] = [
  { id: 'text', label: '文本', type: 'text' },
  { id: 'image', label: '图片', type: 'image', editor: 'edit' },
  { id: 'video', label: '视频', type: 'video', editor: 'video' },
  { id: 'audio', label: '音频', type: 'audio', editor: 'audio' },
  { id: 'compose',label:'编排导出',type:'compose',hint:'连接视频 · 调整顺序 · 合成导出' },
  { id: 'imageGeneration', label: '图片生成', type: 'imageGeneration', editor: 'edit', hint: '文生图 / 图生图' },
  { id: 'videoGeneration', label: '视频生成', type: 'videoGeneration', editor: 'video', hint: '文生视频 / 图生视频' },
  { id: 'audioGeneration', label: '音频生成', type: 'audioGeneration', editor: 'audio', hint: '文本转语音' },
  { id: 'frameAnalysis', label: '逐帧拉片', type: 'frameAnalysis', hint: '镜头检测 · 分镜图 · 动态片段 · 原音轨' },
  { id: 'director3d', label: '3D 导演台', type: 'director3d', hint: '三维机位与角色摆位' },
  { id: 'group', label: '分类框', type: 'group', hint: '归纳所选节点，或创建空框' },
  {
    id: 'group:library',
    label: '素材库',
    children: [
      { id: 'library_assets', label: '项目资产', action: 'assets' },
      { id: 'library_history', label: '生成历史', action: 'history' },
      { id: 'library_upload', label: '本地上传', action: 'upload' },
    ],
  },
]

// Keep legacy renderers/data intact; expose one entry per everyday content type.
export const NODE_CATALOG = FULL_NODE_CATALOG.filter((item) => ['text', 'image', 'video', 'audio', 'compose', 'group', 'group:library'].includes(item.id))

export const NODE_TYPE_LABEL: Record<string, string> = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
  imageGeneration: '图片生成',
  videoGeneration: '视频生成',
  audioGeneration: '音频生成',
  frameAnalysis: '逐帧拉片',
  director3d: '3D 导演台',
  script: '剧本',
  asset: '资产',
  task: '任务',
  group: '分组',
  // 漫剧 / 资产库常见类型（旧画布可能已落库）
  scene: '场景',
  character: '角色',
  prop: '道具',
  shot: '分镜镜头',
  voice: '音色',
  material: '素材',
  // 兼容旧画布扩展类型
  compose: '剪辑合成',
  motion: '动作控制',
  inpaint: '局部重绘',
  outpaint: '扩展画面',
  storyboard: '分镜',
  director_flow: '导演工作流',
  task_flow: '任务工作流',
  recipe: '配方',
  interpolate: '插帧',
  control_video: '控制视频',
  upscale: '超分',
  fill_frames: '补帧',
}
