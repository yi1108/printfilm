import { printfilmStudioApi } from '../api'
import { textWritingPrompt, WRITING_SKILLS } from '../canvas/textWriting'
import { writingContext, writingRequest } from '../canvas/writingContext'
import type { BatchSettings } from './batchGeneration'
import type { StoryNode, StoryEdge } from './storyWorkflow'
import { currentTextModel } from '../modelPreferences'

export async function runWritingNode(projectId: number, node: StoryNode, nodes: StoryNode[], edges: StoryEdge[], settings: BatchSettings, headers: HeadersInit, signal: AbortSignal) {
  const context = writingContext(node, nodes, edges, settings)
  const references = context.references
  const ids = references.map(item => item.id)
  const skill = String(node.data.writingSkill || 'none')
  const prompt = textWritingPrompt(context.outputs.length && context.outputs.every(output=>output.kind==='image') && (!node.data.writingType || node.data.writingType==='镜头提示词') ? '图片提示词' : String(node.data.writingType || '镜头提示词'), skill === 'custom' ? String(node.data.customWritingSkill || '') : WRITING_SKILLS.find(item => item.id === skill)?.text || '', writingRequest(String(node.data.writingPrompt || ''), context.references, context.outputs), String(node.data.text || ''), references)
  signal.throwIfAborted()
  const session = await printfilmStudioApi.createSession(projectId)
  const stop = () => { void printfilmStudioApi.stopSession(session.id).catch(() => undefined) }
  signal.addEventListener('abort', stop, { once: true })
  try {
    signal.throwIfAborted()
    await printfilmStudioApi.updateSession(session.id, { title: `节点写作 · ${node.data.label || '提示词'}`.slice(0, 200), model_id: currentTextModel(String(node.data.writingModel || ''), currentTextModel(settings.textModel || '')) })
    let result = '', error = ''
    await printfilmStudioApi.stream(session.id, prompt, event => {
      if (event.type === 'message_delta') result += String(event.content || '')
      if (event.type === 'error') error = String(event.message || '写作失败')
    }, signal, headers, { enabled_tools: [], node_ids: [node.id, ...ids], agent_mode:'director',skill_task:context.outputs.some(output=>output.kind==='video') ? 'video_prompt' : context.outputs.length ? 'asset_plan' : 'script_write',skill_ids:Array.isArray(node.data.writingDirectorSkillIds) ? node.data.writingDirectorSkillIds.map(Number) : undefined })
    signal.throwIfAborted()
    if (error || !result.trim()) throw new Error(error || '写作模型没有返回正文')
    return result
  } finally { signal.removeEventListener('abort', stop) }
}
