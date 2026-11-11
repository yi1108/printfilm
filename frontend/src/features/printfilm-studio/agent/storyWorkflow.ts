export type StoryNode = { id: string; type?: string; parentId?: string; data: Record<string, unknown> }
export type StoryEdge = { source: string; target: string }
export type StoryStage = 'assets' | 'shots'
export type StoryShot = {
  id: string; label: string; index: number; prompt?: StoryNode; video?: StoryNode; legacy?: StoryNode
  missingLinks: string[]; missingReferences: string[]; canGenerate: boolean
}

const names = (value: unknown): string[] | undefined => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined
const ids = (value: unknown): string[] => names(value) || []
const text = (node: StoryNode) => String(node.data.text || node.data.prompt || '').trim()
export const storyNodeLabel = (node: StoryNode) => String(node.data.label || node.data.name || '未命名节点').split('\n')[0].replace(/^[#*\s]+|[*\s]+$/g, '')
const assetKind = (node: StoryNode) => ['character', 'scene'].includes(String(node.data.storyKind)) ? String(node.data.storyKind) : ['character', 'scene'].includes(String(node.type)) ? node.type : undefined
const isPrompt = (node: StoryNode) => node.data.storyKind === 'shot_prompt' || node.type === 'text' && !node.data.storyKind && /分镜|镜头/.test(storyNodeLabel(node)) && !!text(node)
const isLegacy = (node: StoryNode) => node.data.storyKind === 'shot' || node.type === 'storyboard'
const isVideo = (node: StoryNode) => ['videoGeneration', 'video'].includes(String(node.type)) && (node.data.storyKind === 'shot_video' || /分镜|镜头/.test(storyNodeLabel(node)))
const order = (node: StoryNode) => Number(node.data.shotIndex) || 0

/** A completed chat message is not evidence that a canvas step was completed. */
export function storyGuide(nodes: StoryNode[], preferredIds: string[] = [], edges: StoryEdge[] = []) {
  const scripts = nodes.filter((node) => (node.type === 'script' || node.type === 'text' && !node.data.storyKind && /剧本|脚本/.test(storyNodeLabel(node)) && !/分镜|镜头/.test(storyNodeLabel(node))) && !!String(node.data.text || '').trim())
  const scriptIds = new Set(scripts.map((node) => node.id))
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const neighbors = new Map<string, Set<string>>()
  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue
    if (!neighbors.has(edge.source)) neighbors.set(edge.source, new Set())
    if (!neighbors.has(edge.target)) neighbors.set(edge.target, new Set())
    neighbors.get(edge.source)!.add(edge.target); neighbors.get(edge.target)!.add(edge.source)
  }
  const owner = (node: StoryNode): string | undefined => {
    if (node.data.sourceScriptId) return String(node.data.sourceScriptId)
    if (scriptIds.has(node.id)) return node.id
    const found = new Set<string>(), seen = new Set<string>(), queue = [node.id]
    for (let index = 0; index < queue.length; index++) {
      const id = queue[index]
      if (seen.has(id)) continue
      seen.add(id)
      const current = byId.get(id)
      if (!current) continue
      if (scriptIds.has(id)) { found.add(id); continue }
      if (current.data.sourceScriptId) { found.add(String(current.data.sourceScriptId)); continue }
      queue.push(...(neighbors.get(id) || []))
    }
    if (found.size === 1) return [...found][0]
    // A single-script canvas can safely adopt legacy typed story nodes. In a
    // multi-script canvas, names alone must never cross-associate stories.
    return found.size === 0 && scripts.length === 1 && (assetKind(node) || isPrompt(node) || isLegacy(node) || isVideo(node)) ? scripts[0].id : undefined
  }
  const preferred = preferredIds.map((id) => byId.get(id)).filter((node): node is StoryNode => !!node).map(owner)
  const script = scripts.find((node) => preferred.includes(node.id)) || scripts.at(-1)
  const related = script ? nodes.filter((node) => node.id !== script.id && owner(node) === script.id) : []
  const hasEdge = (source: string, target: string) => edges.some((edge) => edge.source === source && edge.target === target)
  const assets = related.filter((node) => !!assetKind(node))
  const characters = assets.filter((node) => assetKind(node) === 'character')
  const scenes = assets.filter((node) => assetKind(node) === 'scene')
  const expectedCharacters = names(script?.data.storyCharacterNames)
  const expectedScenes = names(script?.data.storySceneNames)
  const missingNames = (expected: string[] | undefined, actual: StoryNode[], fallback: string) => expected
    ? expected.filter((name) => !actual.some((node) => storyNodeLabel(node) === name || storyNodeLabel(node).includes(name)))
    : actual.length ? [] : [fallback]
  const missingCharacters = missingNames(expectedCharacters, characters, '角色')
  const missingScenes = missingNames(expectedScenes, scenes, '场景')
  const assetLinksReady = !!script && assets.every((node) => owner(node) === script.id)
  const assetsReady = !!script && !missingCharacters.length && !missingScenes.length && assets.length > 0 && assets.every((node) => !!text(node) || !!String(node.data.writingRequirements || byId.get(String(node.data.promptNodeId))?.data.writingPrompt || '').trim()) && assetLinksReady
  const prompts = related.filter(isPrompt)
  const videos = related.filter(isVideo)
  const legacy = related.filter(isLegacy)
  const used = new Set<string>()
  const shotPlans: StoryShot[] = []
  const makeShot = (prompt?: StoryNode, video?: StoryNode, old?: StoryNode): StoryShot => {
    const representative = prompt || old || video!
    const missingLinks: string[] = []
    if (!prompt || !String(prompt.data.text || prompt.data.writingPrompt || '').trim()) missingLinks.push('提示词文本节点')
    if (!video) missingLinks.push('视频生成节点')
    if (prompt && video && !hasEdge(prompt.id, video.id)) missingLinks.push('提示词到视频的连线')
    const declared = [...ids(video?.data.referenceNodeIds), ...ids(prompt?.data.referenceNodeIds), ...ids(old?.data.referenceNodeIds)]
    const incoming = video ? edges.filter((edge) => edge.target === video.id && assets.some((node) => node.id === edge.source)).map((edge) => edge.source) : []
    const referenceIds = [...new Set([...declared, ...incoming])]
    const references = referenceIds.map((id) => byId.get(id))
    if (!references.some((node) => node && assets.includes(node) && assetKind(node) === 'scene')) missingLinks.push('场景参考节点及连线')
    const missingReferences: string[] = []
    references.forEach((node, index) => {
      if (!node || !assets.includes(node)) { missingReferences.push('已删除或不属于当前剧本的参考图'); return }
      if (video && !hasEdge(referenceIds[index], video.id)) missingLinks.push(`${storyNodeLabel(node)}的参考连线`)
      if (storyImageState(node) !== 'completed') missingReferences.push(storyNodeLabel(node))
    })
    return { id: representative.id, label: storyNodeLabel(representative), index: order(representative), prompt, video, legacy: old,
      missingLinks: [...new Set(missingLinks)], missingReferences: [...new Set(missingReferences)], canGenerate: !!video && missingLinks.length === 0 && missingReferences.length === 0 && !!String(prompt?.data.text || '').trim() }
  }
  for (const prompt of prompts) {
    const video = videos.find((node) => !used.has(node.id) && (node.data.promptNodeId === prompt.id || prompt.data.videoNodeId === node.id || hasEdge(prompt.id, node.id)))
      || videos.find((node) => !used.has(node.id) && order(prompt) > 0 && order(node) === order(prompt))
    if (video) used.add(video.id)
    shotPlans.push(makeShot(prompt, video))
  }
  for (const video of videos) if (!used.has(video.id)) shotPlans.push(makeShot(undefined, video))
  for (const old of legacy) {
    if (old.data.migratedToPromptId && prompts.some((node) => node.id === old.data.migratedToPromptId)) continue
    if (old.data.storyKind === 'shot' && order(old) > 0 && shotPlans.some((item) => item.index === order(old))) continue
    shotPlans.push(makeShot(undefined, undefined, old))
  }
  shotPlans.sort((a, b) => a.index - b.index)
  const shots = shotPlans.map((item) => item.prompt || item.legacy || item.video!)
  const planningReady = shotPlans.length > 0
  const graphReady = planningReady && shotPlans.every((item) => item.missingLinks.length === 0)
  return { scripts, script, assets, characters, scenes, shots, shotPlans, assetsReady, planningReady, graphReady,
    shotsReady: planningReady, assetLinksReady, missingCharacters, missingScenes,
    needsRepair: assets.length > 0 && !assetsReady || planningReady && !graphReady }
}

export function storyStagePrompt(stage: StoryStage, script: StoryNode) {
  const title = storyNodeLabel(script)
  return stage === 'assets'
    ? `从《${title}》补齐角色与场景的写作节点和图片节点。写作节点只填写生成提示词的写作要求，正文留空，运行时再按实际素材和下游模型生成最终提示词。剧本保持独立不连线，保留已有素材，先不生成图片。`
    : `将《${title}》按故事顺序规划为尽量少的完整视频片段，优先每段 12–15 秒，单段不超过 15 秒。将同场连续动作、对白与反应合并在一个片段中，内部景别变化不另建节点；仅在超过 15 秒或必要的时空转换时拆分，保留完整剧情和对白，不为凑时长添加空等。每个片段创建一个写作节点与视频节点，明确 duration 和 ratio。写作节点只填写生成镜头提示词的写作要求，正文留空；对应角色图、场景图连接到写作节点及视频节点，写作节点连接视频节点。运行时先完成参考素材，再生成最终镜头提示词，先不生成视频。`
}

export function storyImageState(node: StoryNode): 'pending' | 'running' | 'completed' | 'failed' {
  const state = String(node.data.status || '')
  if (['queued', 'running', 'awaiting_composite'].includes(state)) return 'running'
  if (['failed', 'error', 'cancelled'].includes(state)) return 'failed'
  const hasMedia = node.data.mediaUrl || node.data.url || Array.isArray(node.data.mediaUrls) && node.data.mediaUrls.length
  const video = node.data.storyKind === 'shot_video' || ['videoGeneration', 'video'].includes(String(node.type))
  return hasMedia || !video && node.data.cover ? 'completed' : 'pending'
}
