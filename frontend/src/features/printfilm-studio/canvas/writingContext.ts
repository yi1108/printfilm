import { nodeMediaKind } from './nodeOperations.ts'
import { collectMediaUrls, clampMediaIndex } from './imageVariants.ts'
import { mentionToken, plainPrompt, splitPrompt, type PromptReference } from './promptMentions.ts'
import { editableWritingRequirements } from './textWriting.ts'
import { studioMediaRatio } from '../mediaRatio.ts'

type WritingNode = { id: string; type?: string; data: Record<string, unknown> }
type WritingEdge = { source: string; target: string }
type RunSettings = { imageModel: string; videoModel: string; imageRatio: string; videoRatio: string; duration: string }
export type WritingOutput = { id: string; label: string; kind: string; model: string; ratio: string; duration: string }
export type WritingReference = PromptReference & { text: string }

/** Bind a run to content and settings, never to node selection or panel visibility. */
export function writingInputSignature(data: Record<string, unknown>, references: WritingReference[], outputs: WritingOutput[]) {
  return JSON.stringify({
    settings: ['writingPrompt', 'writingType', 'writingSkill', 'writingModel', 'writingDirectorSkillIds', 'customWritingSkill'].map(key => data[key]),
    references,
    outputs: writingOutputSignature(outputs),
  })
}

/** Position/selection updates do not change writing inputs. Resolve each node once
 * until node data or connection endpoints change. */
export function createWritingReferenceResolver() {
  let previousNodes: WritingNode[] = [], previousEdges: WritingEdge[] = []
  const cache = new Map<string, WritingReference[]>()
  return (id: string, nodes: WritingNode[], edges: WritingEdge[]) => {
    if (nodes!==previousNodes || edges!==previousEdges) {
      const changed=nodes.length!==previousNodes.length || edges.length!==previousEdges.length ||
        nodes.some((node,index)=>node.id!==previousNodes[index]?.id || node.type!==previousNodes[index]?.type || node.data!==previousNodes[index]?.data) ||
        edges.some((edge,index)=>edge.source!==previousEdges[index]?.source || edge.target!==previousEdges[index]?.target)
      if(changed) cache.clear()
      previousNodes=nodes;previousEdges=edges
    }
    if(!cache.has(id)) {
      const node=nodes.find(item=>item.id===id)
      cache.set(id,node ? writingContext(node,nodes,edges).references : [])
    }
    return cache.get(id)!
  }
}

// These variants share the same natural-language shot contract, not availability.
export function writingModelFamily(model: string) {
  return /^(?:doubao-)?seedance-2[.-][05](?:-fast)?(?:-\d{6})?$/i.test(model) ? 'seedance-2' : model
}

/** Both the single-node editor and dependency runner resolve the current graph. */
export function writingContext(node: WritingNode, nodes: WritingNode[], edges: WritingEdge[], settings?: RunSettings) {
  const outputs = nodes.filter(item => ['image','video'].includes(nodeMediaKind(item)) &&
    (item.data.promptNodeId === node.id || node.data.outputNodeId === item.id || edges.some(edge => edge.source === node.id && edge.target === item.id)))
  const ids = new Set(edges.filter(edge => edge.target === node.id).map(edge => edge.source))
  for (const id of Array.isArray(node.data.referenceNodeIds) ? node.data.referenceNodeIds : []) ids.add(String(id))
  if (node.data.sourceScriptId) ids.add(String(node.data.sourceScriptId))
  for (const part of splitPrompt(String(node.data.text || ''))) if ('reference' in part && part.reference.source === 'node') ids.add(part.reference.id)
  for (const output of outputs) {
    for (const id of Array.isArray(output.data.referenceNodeIds) ? output.data.referenceNodeIds : []) ids.add(String(id))
    edges.filter(edge => edge.target === output.id && edge.source !== node.id).forEach(edge => ids.add(edge.source))
  }
  const references: WritingReference[] = nodes.filter(item => item.id !== node.id && item.type !== 'group' && ids.has(item.id) &&
    (!node.data.sourceScriptId || !item.data.sourceScriptId || item.data.sourceScriptId === node.data.sourceScriptId)).map(item => {
    const urls = collectMediaUrls(item.data), url = urls[clampMediaIndex(item.data.mediaIndex, urls.length)]
    const promptNode = nodes.find(writer => writer.id === item.data.promptNodeId)
    return { id: item.id, source: 'node', label: String(item.data.label || item.id), url, mediaKind: nodeMediaKind(item),
      text: String(item.data.text || item.data.writingRequirements || item.data.prompt || '') + (promptNode ? `\n参考图提示词：${promptNode.data.text || ''}` : '') + (url ? `\n素材地址：${url}` : '') }
  })
  const parameters: WritingOutput[] = outputs.map(item => {
    const video = nodeMediaKind(item) === 'video'
    return { id: item.id, label: String(item.data.label || item.id), kind: video ? 'video' : 'image',
      model: String(item.data.modelId || (video ? settings?.videoModel : settings?.imageModel) || ''),
      ratio: studioMediaRatio(video ? 'video' : 'image', item.data.ratio || (video ? settings?.videoRatio : settings?.imageRatio)),
      duration: video ? String(item.data.duration || settings?.duration || '').replace(/\s*(秒|s)$/i,'') : '' }
  })
  if (parameters.some(output=>output.kind==='video') && node.data.shotDescription) {
    const siblings = nodes.filter(item=>item.data.storyKind==='shot_prompt' && item.data.sourceScriptId===node.data.sourceScriptId && item.data.sceneNodeId===node.data.sceneNodeId && item.data.sceneNumber===node.data.sceneNumber && item.data.episodeNumber===node.data.episodeNumber && item.data.episodeId===node.data.episodeId).sort((a,b)=>Number(a.data.shotIndex || 0)-Number(b.data.shotIndex || 0))
    const at = siblings.findIndex(item=>item.id===node.id)
    const contextText = `本镜原始分镜：${node.data.shotDescription}\n${siblings.filter((_,i)=>at>=0 && Math.abs(i-at)===1).map(item=>`${Number(item.data.shotIndex)<Number(node.data.shotIndex)?'前镜':'后镜'}（只作衔接）：${item.data.shotDescription || ''}`).join('\n')}`
    if (references.length) references[0] = {...references[0],text:contextText + '\n' + references[0].text}
  }
  return { references, outputs: parameters }
}

/** Keep editable prose and stable mention tokens; only the unique output owns timing. */
export function linkedWritingPrompt(value: string, references: WritingReference[], outputs: WritingOutput[]) {
  let prompt = value
  const videos = outputs.filter(output => output.kind === 'video')
  const pictures = references.filter(item => item.mediaKind === 'image')
  const labels = pictures.filter(item => item.label.length >= 2 && pictures.filter(other => other.label === item.label).length === 1).sort((a,b) => b.label.length-a.label.length)
  prompt = splitPrompt(prompt).map(part => {
    if ('token' in part) return references.some(ref=>ref.id===part.reference.id) ? part.token : part.reference.label
    let prose = part.text
    if (videos.length === 1) {
      if (videos[0].duration) prose = prose.replace(/(总时长|片长|镜头时长|时长|约)\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:秒|s\b)/gi, `$1 ${videos[0].duration} 秒`)
      if (videos[0].ratio && videos[0].ratio !== 'auto') prose = prose.replace(/\b\d{1,2}\s*[:：]\s*\d{1,2}\b/g, videos[0].ratio)
    }
    // Split once around the longest matching label; never rewrite inside a token.
    const tokenize = (text: string, index: number): string => {
      if (index >= labels.length) return text
      const ref = labels[index]
      const escaped = ref.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const pattern = new RegExp(`(?<![A-Za-z0-9_])@?${escaped}(?![A-Za-z0-9_])`, 'g')
      return text.split(pattern).map(piece => tokenize(piece,index+1)).join(mentionToken(ref))
    }
    return tokenize(prose,0)
  }).join('')
  const included = new Set(splitPrompt(prompt).flatMap(part => 'reference' in part ? [part.reference.id] : []))
  const missing = pictures.filter(item => !included.has(item.id))
  if (missing.length) prompt += `\n参考图片：${missing.map(mentionToken).join('、')}`
  return prompt
}

export function writingOutputInstruction(outputs: WritingOutput[]) {
  if (!outputs.length) return ''
  return '\n\n下游实际生成参数（优先于旧正文或创作要求中的时长、比例，不得改写为其他数值）：\n' + outputs.map(output =>
    `${output.label}：模型 ${output.model || '跟随平台默认'}，比例 ${output.ratio || '未设置'}${output.kind === 'video' ? `，时长 ${output.duration ? `${output.duration} 秒` : '未设置'}` : ''}`).join('\n')
}

export function writingRequest(prompt: string, references: WritingReference[], outputs: WritingOutput[]) {
  const pictures = references.filter(ref => ref.mediaKind === 'image')
  return plainPrompt(linkedWritingPrompt(editableWritingRequirements(prompt),references,outputs)) + writingOutputInstruction(outputs)
    + (pictures.length ? '\n图片引用标记（在正文提及对应人物或场景时原样使用，标记不是网址；不要自行编造编号）：\n' + pictures.map(ref => `${ref.label}：${mentionToken(ref)}`).join('\n') : '')
}

/** Restore image identities after text-only models paraphrase or omit the markers. */
export function linkedWritingResult(text: string, references: WritingReference[]) {
  return text.trim() ? linkedWritingPrompt(text.trim(), references, []) : text
}

export function writingOutputSignature(outputs: WritingOutput[]) {
  return JSON.stringify(outputs.map(({id,model,ratio,duration})=>({id,model,ratio,duration})).sort((a,b)=>a.id.localeCompare(b.id)))
}

export function writingParametersChanged(writer: WritingNode, outputs: WritingOutput[]) {
  const saved = writer.data.writingOutputSettings
  if (!Array.isArray(saved)) return false
  return outputs.some(output => {
    const before = saved.find(item => item && item.id === output.id)
    return before && (['model','ratio','duration'] as const).some(key => before[key] && output[key] &&
      (key === 'model' ? writingModelFamily(String(before[key])) !== writingModelFamily(output[key]) : String(before[key]) !== output[key]))
  })
}

export function assertWritingParameters(writer: WritingNode | undefined, output: WritingOutput) {
  if (writer && writingParametersChanged(writer,[output])) throw new Error('下游视频的模型、时长或比例已变化，请重新生成关联的提示词后再运行')
}

export function toggleWritingReference<T extends WritingNode, E extends WritingEdge & {id: string}>(writer: T, nodes: T[], edges: E[], referenceId: string) {
  const source = nodes.find(node => node.id === referenceId)
  if (!source || source.id === writer.id) throw new Error('参考节点不存在')
  if (writer.data.sourceScriptId && source.data.sourceScriptId && writer.data.sourceScriptId !== source.data.sourceScriptId) throw new Error('请使用同一剧本的参考图片')
  const image = nodeMediaKind(source) === 'image'
  const context = writingContext(writer,nodes,edges)
  const targets = new Set([writer.id, ...(image ? context.outputs.filter(output=>output.kind==='video').map(output=>output.id) : [])])
  const removing = context.references.some(ref=>ref.id===referenceId)
  const nextEdges = edges.filter(edge => !(removing && edge.source === referenceId && targets.has(edge.target)))
  if (!removing) for (const target of targets) if (!nextEdges.some(edge=>edge.source===referenceId && edge.target===target)) nextEdges.push({id:`edge-${crypto.randomUUID()}`,source:referenceId,target} as E)
  const nextNodes = nodes.map(node => {
    if (!image || !targets.has(node.id)) return node
    const ids = [...new Set([...(Array.isArray(node.data.referenceNodeIds) ? node.data.referenceNodeIds.map(String) : []), ...edges.filter(edge=>edge.target===node.id && nodes.some(item=>item.id===edge.source && nodeMediaKind(item)==='image')).map(edge=>edge.source)])]
    return {...node,data:{...node.data,referenceNodeIds:removing ? ids.filter(id=>id!==referenceId) : [...new Set([...ids,referenceId])]}}
  })
  return { nodes: nextNodes, edges: nextEdges, removing }
}
