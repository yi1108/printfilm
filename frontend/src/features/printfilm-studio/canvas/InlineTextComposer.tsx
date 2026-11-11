import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { ArrowUp, LoaderCircle, Plus, Square, X } from 'lucide-react'
import { ComposerMenu, ComposerSelect } from './ComposerMenu'
import { WRITING_SKILLS, WRITING_TYPES, textWritingPrompt } from './textWriting'
import { PromptInput } from './PromptInput'
import { StudioModelSelect } from '../StudioModelSelect'
import { editableWritingRequirements, imageWritingRequirements } from './textWriting'
import { linkedWritingPrompt, linkedWritingResult, writingRequest, writingOutputSignature, writingParametersChanged, type WritingOutput, type WritingReference } from './writingContext'
import { listAgentSkills, type AgentSkill } from '../../../api/agentSkills'
import { defaultStudioSkillSelection, studioSkillsForTask, studioSkillName } from '../agent/skills'
import { printfilmStudioApi } from '../api'
import { WritingRunStore } from './WritingRunStore'
import { points } from '../../../lib/points'

type TextReference = { id: string; label: string; text: string; url?: string; mediaKind?: string }
export function InlineTextComposer({ projectId, nodeId, title, text, settings, references, candidates, headers, writable, onSetting, onReference, onFocusReference, onBusy, onApply, onValidate, runStore: providedRunStore, outputs = [] }: {
  projectId: number; nodeId: string; title: string; text: string; settings: Record<string, unknown>; references: TextReference[]; candidates: TextReference[]; headers: HeadersInit; writable: boolean
  onSetting: (key: string, value: string | number[]) => void; onReference: (id: string) => void; onBusy: (busy: boolean) => void; onApply: (text: string, expected: string, outputs?: WritingOutput[]) => void
  onFocusReference?: (id:string)=>void; onRunDependencies?: () => void; outputs?: WritingOutput[]
  runStore?: WritingRunStore; onValidate?: () => void
}) {
  const [directorReady,setDirectorReady] = useState(false)
  const [directorSkills,setDirectorSkills] = useState<AgentSkill[]>([])
  const writingTask = outputs.some(output=>output.kind==='video') ? 'video_prompt' : outputs.length ? 'asset_plan' : 'script_write'
  const configuredIds = Array.isArray(settings.writingDirectorSkillIds) ? settings.writingDirectorSkillIds.map(Number) : undefined
  const directorId = configuredIds ? configuredIds[0] : defaultStudioSkillSelection(directorSkills)[writingTask]
  const [models, setModels] = useState<{ id: string; label: string }[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [elapsed,setElapsed] = useState(0)
  const [localRunStore] = useState(() => new WritingRunStore(id => printfilmStudioApi.stopSession(id)))
  const runStore = providedRunStore || localRunStore, runKey = `${projectId}:${nodeId}`
  const { busy, error, result, startedAt } = useSyncExternalStore(
    useCallback(listener => runStore.subscribe(runKey, listener), [runStore, runKey]),
    useCallback(() => runStore.snapshot(runKey), [runStore, runKey]),
  )
  const setError = (error: string) => runStore.update(runKey, { error })
  const setResult = (result: string) => runStore.update(runKey, { result })
  const [manage, setManage] = useState(false)
  const alive = useRef(true)
  const imageOutput = outputs.length > 0 && outputs.every(output=>output.kind==='image')
  const prompt = (imageOutput ? imageWritingRequirements : editableWritingRequirements)(String(settings.writingPrompt || '')), type = imageOutput && (!settings.writingType || settings.writingType==='镜头提示词') ? '图片提示词' : String(settings.writingType || (outputs.some(output=>output.kind==='video') ? '镜头提示词' : '故事脚本')), skill = String(settings.writingSkill || 'none')
  const boundReferences: WritingReference[] = references.map(item => ({...item,source:'node',mediaKind:item.mediaKind || (item.url ? 'image' : 'text')}))
  const linkedPrompt = linkedWritingPrompt(prompt,boundReferences,outputs)
  const latestOutputs = useRef(outputs); latestOutputs.current = outputs
  const model = models.find(item=>item.id===settings.writingModel)?.id || models.find(item=>item.id===defaultModel)?.id || models[0]?.id || ''
  const requestVersion = useRef('')
  requestVersion.current = JSON.stringify({prompt,type,skill,model,directorId,custom:settings.customWritingSkill,references})
  useEffect(() => { alive.current = true; void printfilmStudioApi.agentConfig().then((value) => { if (alive.current) { setModels(value.models); setDefaultModel(value.default_model || '') } }).catch(() => { if (alive.current) setError('文字模型加载失败') }); return () => { alive.current = false } }, [])
  useEffect(()=>{ let active=true; void listAgentSkills().then(result=>{if(active)setDirectorSkills(result.items || [])}).catch(()=>undefined).finally(()=>{if(active)setDirectorReady(true)}); return()=>{active=false} },[])
  useEffect(()=>{ if(!busy) return; const tick=()=>setElapsed(Math.floor((Date.now()-startedAt)/1000)); tick(); const timer=window.setInterval(tick,1000); return()=>window.clearInterval(timer) },[busy,startedAt])
  const stop = () => runStore.stop(runKey)
  const generate = async () => {
    if (!writable || !directorReady || !prompt.trim() || !model) return
    const run = runStore.begin(runKey)
    if (!run) return
    const expected = text, acceptedOutputs = outputs, binding = writingOutputSignature(outputs), version = requestVersion.current
    onBusy(true)
    let output = ''
    try {
      const session = await printfilmStudioApi.createSession(projectId); run.sessionId = session.id
      if (run.controller.signal.aborted) { await printfilmStudioApi.stopSession(session.id); return }
      await printfilmStudioApi.updateSession(session.id, { title: `文本生成 · ${title}`.slice(0, 200), model_id: model })
      let failure = ''
      await printfilmStudioApi.stream(session.id, textWritingPrompt(type, skill === 'custom' ? String(settings.customWritingSkill || '') : WRITING_SKILLS.find((item) => item.id === skill)?.text || '', writingRequest(prompt,boundReferences,acceptedOutputs), text, references), (event) => {
        if (event.type === 'message_delta') output += String(event.content || '')
        if (event.type === 'error') failure = String(event.message || '文本生成失败')
      }, run.controller.signal, headers, { enabled_tools: [], node_ids: [nodeId, ...references.map((item) => item.id)], agent_mode:'director',skill_task:writingTask,skill_ids:directorId ? [directorId] : [] })
      if (run.controller.signal.aborted) return
      if (failure) throw new Error(failure)
      if (!output.trim()) throw new Error('模型没有返回正文，请重试')
      if (version !== requestVersion.current) throw new Error('写作要求、技能或参考素材已变化，本次结果已保留，请按新要求重新生成')
      if (binding !== writingOutputSignature(latestOutputs.current)) throw new Error('下游视频参数已变化，本次结果已保留，请按新参数重新生成')
      onValidate?.()
      const linked = acceptedOutputs.length ? linkedWritingResult(output, boundReferences) : output
      setResult(linked)
      if (acceptedOutputs.length) onApply(linked, expected, acceptedOutputs); else onApply(linked, expected)
    } catch (reason) { if (!run.controller.signal.aborted) { setResult(output); setError(reason instanceof Error ? reason.message : '文本生成失败') } }
    finally { if (runStore.finish(runKey, run)) onBusy(false) }
  }
  return <div className="pf-composer-card is-attached pf-inline-writing" onMouseDown={(event) => event.stopPropagation()}>
    <div className="pf-composer-tags"><ComposerMenu label="引用故事素材" value={<><Plus size={16} />参考素材</>}>{(close) => <>{candidates.length ? candidates.map((item) => <button key={item.id} disabled={busy || !writable} onClick={() => { onReference(item.id); close() }}>{item.url && <img className="pf-writing-reference-thumb" src={item.url} alt=""/>}{item.label}</button>) : <p>暂无其他文本或图片节点</p>}</>}</ComposerMenu>{references.map((item) => <span className="pf-chip is-ref" key={item.id}><button type="button" className="pf-ref-jump" aria-label={`定位关联节点 ${item.label}`} onClick={()=>onFocusReference?.(item.id)}>{item.url && <img className="pf-writing-reference-thumb" src={item.url} alt=""/>}{item.label}</button><button aria-label={`移除参考 ${item.label}`} disabled={busy || !writable} onClick={() => onReference(item.id)}><X size={12}/></button></span>)}</div>
    <div className="pf-writing-prompt"><PromptInput label="AI 写作要求" value={linkedPrompt} references={boundReferences} readOnly={busy || !writable} onChange={value => onSetting('writingPrompt', value)} placeholder="输入写作要求，参考图片会显示为关联素材" /></div>
    {!!outputs.length && <div className="pf-writing-outputs" aria-label="下游生成参数">{outputs.map(output => <span key={output.id}><b>{output.label}</b> · {output.model || '平台默认模型'} · {output.ratio || '未设置比例'}{output.kind === 'video' ? ` · ${output.duration ? `${output.duration} 秒` : '未设置时长'}` : ''}</span>)}<small>{imageOutput ? '按动漫风格生成图片提示词，保留角色与场景特征，比例跟随下游图片节点。' : '按图片名称与已有描述写作，图片会用于下游视频生成。时长、比例跟随下游节点。'}</small></div>}
    {text.trim() && writingParametersChanged({id:nodeId,data:settings},outputs) && <p className="pf-composer-validation">下游参数已变化，请重新生成提示词，避免使用旧时长或比例。</p>}
    <fieldset disabled={busy || !writable} className="pf-writing-director"><ComposerSelect label="导演写作技能" value={directorId ? String(directorId) : ''} options={[{id:'',label:'不使用导演技能'},...studioSkillsForTask(directorSkills,writingTask).map(skill=>({id:String(skill.id),label:imageOutput && skill.is_builtin && skill.slug==='short-drama-assets' ? '图片提示词导演' : studioSkillName(skill)}))]} onChange={value=>onSetting('writingDirectorSkillIds',value ? [Number(value)] : [])}/></fieldset>
    <footer><fieldset disabled={busy || !writable} className="pf-writing-parameters"><ComposerSelect label="写作类型" value={type} options={WRITING_TYPES.map((id) => ({ id, label: id }))} onChange={(value) => onSetting('writingType', value)} /><StudioModelSelect label="文字模型" value={model} options={models} onChange={(value) => onSetting('writingModel', value)} /><ComposerSelect label="附加写作规范" value={skill} options={[...WRITING_SKILLS, { id: 'custom', label: '自定义技能' }, { id: 'manage', label: '管理技能…' }]} onChange={(value) => value === 'manage' ? setManage(!manage) : onSetting('writingSkill', value)} /></fieldset><span className="pf-composer-spacer" /><em className="pf-composer-cost">{points(5)} / 次</em>{busy ? <button className="pf-composer-go" aria-label="停止写作" onClick={stop}><Square size={17} /></button> : <button className="pf-composer-go" aria-label="开始 AI 写作" disabled={!writable || !directorReady || !prompt.trim() || !model} onClick={() => void generate()}><ArrowUp size={18} /></button>}</footer>
    {manage && <div className="pf-writing-skill-editor"><b>自定义写作技能</b><textarea aria-label="自定义技能规范" maxLength={3000} value={String(settings.customWritingSkill || '')} onChange={(event) => onSetting('customWritingSkill', event.target.value)} placeholder="填写输出格式、叙事风格或其他写作规则" /><button onClick={() => { onSetting('writingSkill', 'custom'); setManage(false) }}>使用此技能</button></div>}
    {busy && <div className="pf-writing-progress" role="status"><LoaderCircle size={15}/><span>正在创作，完成后写入节点</span><small>{elapsed} 秒 · 可关闭面板</small></div>}
    {error && <div role="alert" className="pf-composer-validation">{error}{result && <details><summary>保留的生成结果</summary><textarea readOnly value={result} aria-label="保留的生成结果" /></details>}</div>}
  </div>
}
