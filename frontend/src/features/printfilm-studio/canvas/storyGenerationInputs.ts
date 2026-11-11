import { splitPrompt } from './promptMentions.ts'

type StoryGenerationNode = { id: string; type?: string; data: Record<string, unknown> }
type StoryGenerationEdge = { source: string; target: string }

export function storyAssetPrompt(source: StoryGenerationNode | undefined, nodes: StoryGenerationNode[], edges: StoryGenerationEdge[]) {
  if (!source || !['character', 'scene'].includes(String(source.data.storyKind)) || !source.data.promptNodeId) return undefined
  const writer = nodes.find((node) => node.id === source.data.promptNodeId)
  if (!writer || !['text', 'script'].includes(writer.type || '') || !edges.some((edge) => edge.source === writer.id && edge.target === source.id)) throw new Error('请连接该参考图的写作文本节点')
  if (writer.data.sourceScriptId !== source.data.sourceScriptId) throw new Error('写作文本必须属于同一剧本')
  const prompt = String(writer.data.text || '').trim()
  if (!prompt) throw new Error('请先填写参考图的写作文本')
  return prompt
}

/** Resolve the live graph at submit time; cached video prompts are not authoritative. */
export function storyVideoInputs(source: StoryGenerationNode | undefined, nodes: StoryGenerationNode[], edges: StoryGenerationEdge[]) {
  if (source?.data.storyKind !== 'shot_video') return undefined
  const incoming = new Set(edges.filter((edge) => edge.target === source.id).map((edge) => edge.source))
  const promptId = String(source.data.promptNodeId || '')
  const promptNode = nodes.find((node) => node.id === promptId)
  if (!promptNode || !incoming.has(promptId) || !['text', 'script'].includes(promptNode.type || '')) throw new Error('请连接该分镜的提示词文本节点')
  const scriptId = String(source.data.sourceScriptId || '')
  if (!scriptId || promptNode.data.sourceScriptId !== scriptId) throw new Error('分镜提示词必须属于同一个剧本')
  const prompt = String(promptNode.data.text || '').trim()
  if (!prompt) throw new Error('分镜提示词为空，请先完善文本节点')
  const ids = Array.isArray(source.data.referenceNodeIds) ? [...new Set(source.data.referenceNodeIds.map(String))] : []
  if (!ids.length) throw new Error('请关联该分镜的角色和场景参考图')
  const references = ids.map((id) => {
    const node = nodes.find((item) => item.id === id)
    if (!node || !incoming.has(id)) throw new Error('分镜参考图连线不完整，请先修复连线')
    if (node.data.sourceScriptId !== scriptId || !['character', 'scene'].includes(String(node.data.storyKind || ''))) throw new Error('分镜参考图必须来自同一剧本的角色或场景')
    const label = String(node.data.label || '参考图')
    if (node.data.mediaType && node.data.mediaType !== 'image') throw new Error(`${label} 不是图片参考`)
    if (['queued', 'running', 'awaiting_composite', 'failed', 'error', 'cancelled'].includes(String(node.data.status || ''))) throw new Error(`请先完成参考图「${label}」的生成`)
    const urls = Array.isArray(node.data.mediaUrls) ? node.data.mediaUrls.filter((url): url is string => typeof url === 'string' && !!url.trim()) : []
    const value = Number(node.data.mediaIndex || 0)
    const index = Number.isFinite(value) ? Math.max(0, Math.min(Math.floor(value), urls.length - 1)) : 0
    const url = urls[index] || String(node.data.mediaUrl || node.data.url || node.data.cover || '')
    if (!url) throw new Error(`请先生成参考图「${label}」`)
    return { node, url }
  })
  if (!references.some((reference) => reference.node.data.storyKind === 'scene')) throw new Error('该分镜缺少场景参考图，请先关联场景')
  const providerPrompt = splitPrompt(prompt).map(part => {
    if ('text' in part) return part.text
    const index = references.findIndex(ref=>part.reference.source === 'node' && ref.node.id === part.reference.id)
    return index >= 0 ? `@图片${index+1}` : part.reference.label
  }).join('') + '\n参考素材对应（按实际上传顺序）：\n' + references.map((ref,index)=>
    `@图片${index+1}：${ref.node.data.label || '参考图'}，${ref.node.data.storyKind === 'scene' ? '用于场景空间与光线' : '仅用于人物身份和造型，不照搬背景或姿势'}。`).join('\n')
  return { prompt, providerPrompt, promptNode, references, mode: 'omni_reference' as const }
}
