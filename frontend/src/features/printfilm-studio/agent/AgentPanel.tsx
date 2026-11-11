import { DirectorSkillPicker } from './DirectorSkillPicker'
import { ComposerSelect } from '../canvas/ComposerMenu'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUp, AtSign, Clapperboard, Minus, Plus, Check, CircleStop, History, MessageSquarePlus, Mic, PanelRight, Pencil, Settings2, Trash2, X, Search } from 'lucide-react'
import { dramaApi } from '../../../api/drama'
import { listAgentSkills, type AgentSkill } from '../../../api/agentSkills'
import { AgentReferences, ReferenceThumbnail } from './AgentReferences'
import { assetReference, nodeReference, type AgentReference } from './references'
import { printfilmStudioApi } from '../api'
import { AgentConversation, type MessageAction } from './AgentConversation'
import { StoryGuide } from './StoryGuide'
import { storyStagePrompt, type StoryStage, type StoryNode } from './storyWorkflow'
import type { AgentEvent } from './conversation'
import { useAgentPanel } from './useAgentPanel'
export type { AgentEvent } from './conversation'
import { useVoiceInput } from './useVoiceInput'
import { proposalStatus, type AgentProposal } from './proposals'
import { emptyStudioSkillSelection, studioSkillOptions, restoreStudioSkillSelection, inferredStudioSkillTask, type StudioSkillSelection, type StudioSkillTask } from './skills'
import type { ProposalControls } from './ProposalCard'
import type { AgentOptions, AgentSession, ProjectAsset } from '../types'

const toolLabels: Record<string, string> = { plan_story_assets: '抽取角色与场景', plan_story_shots: '拆分分镜', edit_media: '剪辑处理媒体', read_project: '读取项目', read_episode: '读取剧集', read_canvas: '读取画布', add_canvas_node: '添加节点', update_canvas_node: '更新节点', remove_canvas_node: '删除节点', connect_canvas_nodes: '连接节点', list_assets: '查询素材', attach_asset_to_node: '绑定素材', create_image_task: '生成图片', create_video_task: '生成视频', create_audio_task: '生成音频', get_task_status: '查询任务', update_script: '更新剧本', update_shot: '更新镜头', estimate_generation_price: '预估价格' }

export function AgentPanel({ projectId, sessionId, events, answer, running, prompt, nodes, edges, assets, headers, writable, onDockWidth, onHistoryChange, onPrompt, onSend, onGenerateMedia, onRepairStory, onStop, onSelectSession, onClose, selectedNodeIds = [], proposals }: {
  proposals?: ProposalControls
  selectedNodeIds?: string[]
  projectId: number; sessionId: string | null; events: AgentEvent[]; answer: string; running: boolean; prompt: string; nodes: { id: string; type?: string; data: Record<string, unknown> }[]; edges: { source: string; target: string }[]; assets: ProjectAsset[]; headers: HeadersInit; writable: boolean
  onDockWidth: (width: number) => void; onHistoryChange: (session: AgentSession) => void
  onPrompt: (value: string) => void; onSend: (options: AgentOptions, model: string, references: AgentReference[], message?: string) => Promise<void>; onGenerateMedia: (id: string, kind: 'image' | 'video') => void; onRepairStory: (scriptId: string) => Promise<void>; onStop: () => void; onSelectSession: (id: string | null) => void; onClose: () => void
}) {
  const [tab, setTab] = useState<'chat' | 'history' | 'settings' | 'mentions'>('chat')
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [models, setModels] = useState<{ id: string; label: string }[]>([])
  const [tools, setTools] = useState<string[]>([])
  const [enabled, setEnabled] = useState<string[] | undefined>()
  const [role, setRole] = useState<'director' | 'assistant'>('director')
  /* 导演 Skill 按阶段单选；列表就绪前阻止导演发送，避免默认规则尚未加载。 */
  const [skillTask, setSkillTask] = useState<StudioSkillTask>('script_write')
  const [skillSelection, setSkillSelection] = useState<StudioSkillSelection>(emptyStudioSkillSelection)
  const [agentSkills, setAgentSkills] = useState<AgentSkill[]>([])
  const [skillsReady, setSkillsReady] = useState(false)
  const skillsProject = useRef<number | null>(null)
  const selectionKey = selectedNodeIds.join(',')
  useEffect(() => { setNodeIds(selectionKey ? selectionKey.split(',').slice(0, 20) : []) }, [selectionKey])
  const [model, setModel] = useState('')
  const modelSession = useRef<string | null | undefined>(undefined)
  const [nodeIds, setNodeIds] = useState<string[]>([])
  const [assetRefs, setAssetRefs] = useState<ProjectAsset[]>([])
  const [error, setError] = useState('')
  const [mentionIndex, setMentionIndex] = useState(0)
  const [mentionScope, setMentionScope] = useState('canvas')
  const [mentionSearch, setMentionSearch] = useState('')
  const [mentionPage, setMentionPage] = useState(1)
  const [libraryAssets, setLibraryAssets] = useState<ProjectAsset[]>([])
  const [libraryLoading, setLibraryLoading] = useState(false)
  useEffect(() => {
    if (tab !== 'mentions' || mentionScope !== 'library') return
    let active = true
    setLibraryLoading(true)
    void dramaApi.listAssets().then((items) => { if (active) setLibraryAssets(items) }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '素材加载失败') }).finally(() => { if (active) setLibraryLoading(false) })
    return () => { active = false }
  }, [tab, mentionScope])
  const settingsId = useId()
  const settingsPanel = useRef<HTMLDivElement>(null)
  const settingsButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (tab !== 'settings') return
    const dismiss = (event: PointerEvent) => {
      if (!settingsPanel.current?.contains(event.target as Node) && !settingsButton.current?.contains(event.target as Node)) setTab('chat')
    }
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { setTab('chat'); settingsButton.current?.focus() }
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', escape) }
  }, [tab])
  const mentionListId = useId()
  const input = useRef<HTMLTextAreaElement>(null)
  const mentionList = useRef<HTMLDivElement>(null)
  const voice = useVoiceInput((text) => onPrompt(prompt + text), setError)
  const [uploading, setUploading] = useState(false)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const layout = useAgentPanel(onDockWidth)
  const upload = useRef<HTMLInputElement | null>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    let active = true
    void printfilmStudioApi.agentConfig().then((config) => { if (active) { setModels(config.models); setTools(config.tools) } }).catch((reason) => { if (active) setError(String(reason.message)) })
    return () => { active = false }
  }, [projectId])
  useEffect(() => {
    let active = true
    setSkillsReady(false)
    void listAgentSkills().then((result) => {
      if (!active) return
      const items = result.items || []
      setAgentSkills(items)
      let stored: unknown
      try { stored = JSON.parse(localStorage.getItem(`pf-director-skills:${projectId}`) || 'null') } catch { stored = null }
      skillsProject.current = projectId
      setSkillSelection(restoreStudioSkillSelection(items,stored))
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '导演 Skill 加载失败') }).finally(() => { if (active) setSkillsReady(true) })
    return () => { active = false }
  }, [projectId])
  useEffect(() => {
    if (!skillsReady || skillsProject.current !== projectId) return
    try { localStorage.setItem(`pf-director-skills:${projectId}`, JSON.stringify(skillSelection)) } catch { /* Private browser storage can be unavailable. */ }
  }, [skillSelection,skillsReady,projectId])
  useEffect(() => {
    let active = true
    void printfilmStudioApi.listSessions(projectId).then((result) => { if (active) { setSessions(result.sessions); if (modelSession.current !== sessionId) { modelSession.current = sessionId; setModel(result.sessions.find((item) => item.id === sessionId)?.model_id || '') } } }).catch((reason) => { if (active) setError(String(reason.message)) })
    return () => { active = false }
  }, [projectId, sessionId, tab, running])
  const attempt = async (action: () => Promise<void>) => { setError(''); try { await action() } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : '操作失败') } }
  const select = (id: string | null) => { onSelectSession(id); setTab('chat'); setNodeIds([]); setAssetRefs([]) }
  const toggleNode = (id: string) => setNodeIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : ids.length < 20 ? [...ids, id] : ids)
  const toggleAsset = (asset: ProjectAsset) => setAssetRefs((items) => items.some((item) => item.id === asset.id) ? items.filter((item) => item.id !== asset.id) : items.length < 20 ? [...items, asset] : items)
  const references = [
    ...nodeIds.flatMap((id) => { const node = nodes.find((item) => item.id === id); return node ? [nodeReference(node, assets)] : [] }),
    ...assetRefs.map(assetReference),
  ]
  const send = () => {
    if (running || uploading || !prompt.trim() || role === 'director' && !skillsReady) return
    const task = inferredStudioSkillTask(prompt,skillTask)
    setSkillTask(task)
    void onSend({
      director_skill_selection: role === 'director' ? skillSelection : undefined,
      enabled_tools: enabled || (role === 'director' ? tools.filter((tool) => !['create_image_task', 'create_video_task', 'create_audio_task'].includes(tool)) : undefined),
      node_ids: references.flatMap((item) => item.nodeId ? [item.nodeId] : []),
      asset_ids: assetRefs.map((item) => item.id),
      ...studioSkillOptions(skillSelection, task, role),
    }, model, references)
  }
  const startStoryStage = (stage: StoryStage, script: StoryNode) => {
    if (running || uploading || !writable || !skillsReady) return
    const required = stage === 'assets' ? 'plan_story_assets' : 'plan_story_shots'
    if (!tools.includes(required)) { setError('创作引导工具尚未加载，请刷新后重试'); return }
    if (enabled && (!enabled.includes(required) || !enabled.includes('read_canvas'))) { setError('请在工具设置中开启读取画布和对应的创作引导工具'); return }
    setTab('chat')
    setNodeIds([script.id])
    setSkillTask(stage==='assets' ? 'asset_plan' : 'shot_plan')
    void onSend({
      director_skill_selection: skillSelection,
      enabled_tools: ['read_canvas', required],
      node_ids: [script.id],
      story_step: stage,
      ...studioSkillOptions(skillSelection, stage === 'assets' ? 'asset_plan' : 'shot_plan', 'director'),
    }, model, [nodeReference(script, assets)], storyStagePrompt(stage, script))
  }
  const mentionQuery = (mentionSearch || /@([^\s@]*)$/.exec(prompt)?.[1] || '').toLowerCase()
  const matches = tab !== 'mentions' ? [] : (mentionScope === 'canvas'
    ? nodes.filter((node) => node.type !== 'group').map((node) => ({ ...nodeReference(node, assets), selected: nodeIds.includes(node.id), pick: () => toggleNode(node.id) }))
    : (mentionScope === 'library' ? libraryAssets : assets).map((asset) => ({ ...assetReference(asset), selected: assetRefs.some((item) => item.id === asset.id), pick: () => toggleAsset(asset) }))
  ).filter((item) => `${item.label} ${item.key}`.toLowerCase().includes(mentionQuery))
  const mentionPages = Math.max(1, Math.ceil(matches.length / 24))
  const currentMentionPage = Math.min(mentionPage, mentionPages)
  const mentionItems = matches.slice((currentMentionPage - 1) * 24, currentMentionPage * 24)
  const activeMention = Math.min(mentionIndex, Math.max(0, mentionItems.length - 1))
  useEffect(() => { setMentionIndex(0); setMentionPage(1) }, [mentionQuery, tab, mentionScope])
  useEffect(() => {
    const list = mentionList.current
    const item = list?.querySelector<HTMLElement>('[data-active="true"]')
    if (!list || !item) return
    if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop
    else if (item.offsetTop + item.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight
  }, [activeMention, tab])
  const pickMention = (item: typeof mentionItems[number]) => {
    if (!item.selected) {
      if (item.key.startsWith('node-') ? nodeIds.length >= 20 : assetRefs.length >= 20) { setError('节点和素材分别最多引用 20 项'); return }
      item.pick()
    }
    onPrompt(`${prompt.replace(/@[^\s@]*$/, '')}@${item.label} `)
    setTab('chat'); input.current?.focus()
  }
  const mentionKey = (event: KeyboardEvent<HTMLElement>) => {
    if (tab !== 'mentions' || event.nativeEvent.isComposing) return false
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', 'Tab', 'Escape'].includes(event.key)) return false
    event.preventDefault(); event.stopPropagation()
    if (event.key === 'Escape') { setTab('chat'); input.current?.focus(); return true }
    if (event.key === 'Enter' || event.key === 'Tab') { if (mentionItems[activeMention] && !event.repeat) pickMention(mentionItems[activeMention]); return true }
    const length = mentionItems.length
    if (length) setMentionIndex(event.key === 'Home' ? 0 : event.key === 'End' ? length - 1 : (activeMention + (event.key === 'ArrowDown' ? 1 : -1) + length) % length)
    return true
  }
  const uploadFiles = (files: FileList | null) => {
    if (!files?.length || !writable || uploading || running) return
    void attempt(async () => {
      setUploading(true)
      try {
        for (const file of Array.from(files).slice(0, Math.max(0, 20 - assetRefs.length))) {
          if (!/^(image|video|audio)\//.test(file.type)) throw new Error('目前支持上传图片、视频或音频作为引用')
          const asset = await printfilmStudioApi.uploadAsset(projectId, file, headers)
          if (!alive.current) return
          toggleAsset(asset)
        }
      } finally { if (alive.current) setUploading(false) }
    })
  }
  const historyAction = async (event: AgentEvent, action: MessageAction) => {
    if (!sessionId || !event.id || running) return
    const sequence = Math.max(...events.map((item) => item.sequence || 0))
    const lastId = events.find((item) => item.sequence === sequence)?.id
    if (!lastId) throw new Error('消息尚未同步完成，请重新打开会话后操作')
    const changed = await printfilmStudioApi.messageAction(sessionId, event.id, action, sequence, lastId)
    if (!alive.current) return
    onHistoryChange(changed)
    if (action === 'edit_branch') onPrompt(event.text)
  }
  return <aside className={`pf-agent-panel ${layout.docked ? 'is-docked' : 'is-floating'}`} style={layout.rect} aria-label="Printfilm Agent" onDragOver={(event) => { if (writable && event.dataTransfer.types.includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' } }} onDrop={(event) => { if (event.dataTransfer.files.length) { event.preventDefault(); uploadFiles(event.dataTransfer.files) } }} {...layout.handlers}>
    {(['left', ...(layout.docked ? [] : ['right', 'bottom'])] as ('left' | 'right' | 'bottom')[]).map((edge) => <div key={edge} className={`pf-agent-resize is-${edge}`} role="separator" aria-label={edge === 'bottom' ? '调整对话高度' : '调整对话宽度'} aria-orientation={edge === 'bottom' ? 'horizontal' : 'vertical'} aria-valuenow={edge === 'bottom' ? layout.rect.height : layout.rect.width} tabIndex={0} onPointerDown={(event) => layout.start(event, edge)} onKeyDown={(event) => layout.keyboard(event, edge)} />)}
    <header className="pf-agent-panel-header" onPointerDown={(event) => layout.start(event, 'move')}>
      <span className="pf-agent-brand" aria-hidden="true">P<span /></span>
      <b title={sessions.find((item) => item.id === sessionId)?.title}>{sessions.find((item) => item.id === sessionId)?.title || '画布创作助手'}</b>
      <button title="新建会话" aria-label="新建会话" disabled={running} onClick={() => select(null)}><MessageSquarePlus size={18} /></button>
      <button title="会话历史" aria-label="会话历史" aria-expanded={tab === 'history'} onClick={() => setTab(tab === 'history' ? 'chat' : 'history')}><History size={18} /></button>
      <button ref={settingsButton} title="工具设置" aria-label="工具设置" aria-expanded={tab === 'settings'} aria-controls={settingsId} onClick={() => setTab(tab === 'settings' ? 'chat' : 'settings')}><Settings2 size={18} /></button>
      <button title={layout.docked ? '切换悬浮面板，可拖动和缩放' : '停靠右侧'} aria-label={layout.docked ? '切换悬浮面板' : '停靠右侧'} onClick={layout.toggleDock}><PanelRight size={18} /></button>
      <button title="收起 Agent" aria-label="收起 Agent" onClick={onClose}><Minus size={18} /></button>
    </header>
    {tab === 'settings' && <div ref={settingsPanel} id={settingsId} className="pf-agent-settings" role="region" aria-label="助手工具设置">
      <div className="pf-agent-settings-heading"><span>助手设置</span><button aria-label="关闭设置" onClick={() => { setTab('chat'); settingsButton.current?.focus() }}><X size={16} /></button></div>
      <p>选择本次对话允许使用的工具</p>
      <div className="pf-agent-settings-tools">{tools.map((tool) => {
        const checked = enabled ? enabled.includes(tool) : role !== 'director' || !['create_image_task', 'create_video_task', 'create_audio_task'].includes(tool)
        return <label className="pf-tool-toggle" key={tool}><span>{toolLabels[tool] || tool}</span><input type="checkbox" role="switch" disabled={running} checked={checked} onChange={(event) => setEnabled((current) => {
          const active = current || (role === 'director' ? tools.filter((item) => !['create_image_task', 'create_video_task', 'create_audio_task'].includes(item)) : tools)
          return event.target.checked ? [...new Set([...active, tool])] : active.filter((item) => item !== tool)
        })} /></label>
      })}{!tools.length && <p>暂无可配置工具</p>}</div>
      <p className="pf-agent-settings-note">{role === 'director' && !enabled ? '导演执导默认只修改画布，不自动运行生成。' : '开启生成工具后，生成任务按现有规则计费。'}</p>
    </div>}
    {tab === 'history' ? <div className="pf-agent-scroll"><h3>会话历史</h3>{sessions.length === 0 && <p>还没有会话，发送消息即可开始。</p>}{sessions.map((session) => <div className="pf-agent-session" key={session.id}>{renaming === session.id ? <><input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /><button title="保存名称" onClick={() => void attempt(async () => { const changed = await printfilmStudioApi.updateSession(session.id, { title }); setSessions((items) => items.map((item) => item.id === changed.id ? changed : item)); setRenaming(null) })}><Check size={16} /></button></> : <><button className="pf-session-name" disabled={running} onClick={() => select(session.id)}>{session.title}<small>{session.status === 'running' ? '执行中' : session.id === sessionId ? '当前会话' : '打开历史'}</small></button><button title="重命名" disabled={session.status === 'running'} onClick={() => { setRenaming(session.id); setTitle(session.title) }}><Pencil size={15} /></button><button title="删除会话" disabled={session.status === 'running'} onClick={() => { if (window.confirm(`删除会话「${session.title}」及其消息？`)) void attempt(async () => { await printfilmStudioApi.deleteSession(session.id); setSessions((items) => items.filter((item) => item.id !== session.id)); if (session.id === sessionId) select(null) }) }}><Trash2 size={15} /></button></>}</div>)}</div>
      : <AgentConversation proposals={proposals} sessionId={sessionId} events={events} answer={answer} running={running} labels={toolLabels} onPrompt={onPrompt} onAction={historyAction} guide={<StoryGuide running={running} pending={!!proposals && events.some((event) => event.type === 'proposal' && ['pending', 'undone'].includes(proposalStatus(event.data as AgentProposal, proposals.states, nodes)))} nodes={nodes} edges={edges} preferredIds={nodeIds.length ? nodeIds : events.findLast((event) => event.type === 'user')?.references?.flatMap((reference) => reference.nodeId ? [reference.nodeId] : []) || []} writable={writable && !uploading} onStage={startStoryStage} onGenerate={onGenerateMedia} onRepair={(scriptId) => { void attempt(() => onRepairStory(scriptId)) }} />} />}

    {error && <div role="alert" className="pf-agent-error">{error}<button aria-label="关闭错误提示" onClick={() => setError('')}><X size={12} /></button></div>}
    <nav className="pf-agent-shortcuts" aria-label="创作快捷操作">
      <button onClick={() => { setTab('mentions'); input.current?.focus() }}>参考素材</button>
      <button disabled={!writable || uploading || running} onClick={() => upload.current?.click()}>上传素材</button>
      <button onClick={() => { onPrompt('读取当前画布的节点与连线，梳理故事结构并给出分镜建议。'); setTab('chat'); input.current?.focus() }}>梳理分镜</button>
    </nav>
    {role === 'director' && <DirectorSkillPicker skills={agentSkills} selection={skillSelection} task={skillTask} disabled={running || !skillsReady} onTask={setSkillTask} onSelect={(phase,id)=>setSkillSelection(current=>({...current,[phase]:id}))}/>}
    <div className="pf-agent-compose">
      {tab === 'mentions' && <div className="pf-agent-mention-menu" onKeyDown={mentionKey}>
        <header><b>引用节点与素材</b><button aria-label="关闭引用菜单" onClick={() => { setTab('chat'); input.current?.focus() }}><X size={14} /></button></header>
        <div className="pf-mention-tabs" role="tablist" aria-label="引用来源">{[['canvas', '当前画布'], ['project', '项目素材'], ['library', '我的素材']].map(([key, label]) => <button key={key} role="tab" aria-selected={mentionScope === key} onClick={() => setMentionScope(key)}>{label}</button>)}</div>
        <label className="pf-mention-search"><Search size={14} /><input aria-label="搜索引用节点或素材" placeholder="搜索节点名称或 ID" value={mentionSearch} onChange={(event) => setMentionSearch(event.target.value)} /></label>
        <div ref={mentionList} id={mentionListId} role="listbox" aria-label="引用节点与素材" aria-multiselectable="true" className="pf-agent-mention-options">
          {mentionItems.map((item, index) => <button key={item.key} id={`${mentionListId}-${index}`} role="option" aria-selected={item.selected} data-active={index === activeMention} onMouseEnter={() => setMentionIndex(index)} onMouseDown={(event) => event.preventDefault()} onClick={() => pickMention(item)}><span className="pf-mention-thumb"><ReferenceThumbnail reference={item} /></span><span className="pf-mention-copy"><b>{item.label}</b><small>{{ image: '图片', video: '视频', audio: '音频', text: '文本' }[item.kind]}</small></span>{item.selected && <Check size={14} />}</button>)}
          {libraryLoading && mentionScope === 'library' && <p>正在加载素材…</p>}
          {mentionItems.length === 0 && <p>没有匹配的节点或素材</p>}
        </div>
        {mentionPages > 1 && <nav className="pf-library-pagination" aria-label="引用分页"><button disabled={currentMentionPage === 1} onClick={() => { setMentionPage(currentMentionPage - 1); setMentionIndex(0) }}>上一页</button><span>{currentMentionPage} / {mentionPages} 页</span><button disabled={currentMentionPage === mentionPages} onClick={() => { setMentionPage(currentMentionPage + 1); setMentionIndex(0) }}>下一页</button></nav>}
        <small className="pf-agent-mention-help">↑ ↓ 选择 · Enter 确认 · Esc 关闭</small>
      </div>}
      <AgentReferences references={references} onRemove={(reference) => {
        if (reference.nodeId) toggleNode(reference.nodeId)
        else setAssetRefs((items) => items.filter((item) => item.id !== reference.assetId))
      }} />
      <textarea ref={input} aria-label="Agent 消息" aria-controls={tab === 'mentions' ? mentionListId : undefined} aria-activedescendant={tab === 'mentions' && mentionItems.length ? `${mentionListId}-${activeMention}` : undefined} aria-autocomplete="list" value={prompt} onChange={(event) => { onPrompt(event.target.value); if (/@[^\s@]*$/.test(event.target.value)) setTab('mentions'); else if (tab === 'mentions') setTab('chat') }} onKeyDown={(event) => { if (mentionKey(event)) return; if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send() } }} placeholder="选择参考素材，或直接输入你的故事和镜头想法…" />
      <footer>
        <div className="pf-agent-compose-tools">
          <button title={writable ? '上传项目素材作为引用' : '需要编辑权才能上传素材'} aria-label="上传素材" disabled={!writable || uploading || running} onClick={() => upload.current?.click()}><Plus size={20} /></button>
          <Clapperboard className="pf-agent-role-icon" size={17} />
          <ComposerSelect label="Agent 工作方式" value={role} options={[{ id: 'director', label: '导演执导' }, { id: 'assistant', label: '通用助手' }]} onChange={(value) => setRole(value === 'assistant' ? 'assistant' : 'director')} />
        </div>
        <div className="pf-agent-compose-actions">
          <select aria-label="Agent 模型" title={models.find((item) => item.id === model)?.label || '默认模型'} value={model} disabled={running} onChange={(event) => setModel(event.target.value)}><option value="">默认模型</option>{models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
          <button title="引用节点与素材" aria-label="引用节点与素材" aria-expanded={tab === 'mentions'} aria-controls={mentionListId} onClick={() => { setTab(tab === 'mentions' ? 'chat' : 'mentions'); input.current?.focus() }}><AtSign size={17} /></button>
          <button title={voice.supported ? voice.recording ? '停止语音输入' : '语音输入（使用浏览器语音识别）' : '当前浏览器不支持语音识别'} aria-label="语音输入" disabled={!voice.supported || running} aria-pressed={voice.recording} onClick={voice.toggle}><Mic size={17} /></button>
          {running ? <button className="pf-agent-send" title="停止执行" aria-label="停止执行" onClick={onStop}><CircleStop size={21} /></button> : <button className="pf-agent-send" title="发送消息" aria-label="发送消息" disabled={!prompt.trim() || uploading || role === 'director' && !skillsReady} onClick={() => { setTab('chat'); send() }}><ArrowUp size={21} /></button>}
        </div>
      </footer></div>
    <input hidden type="file" multiple accept="image/*,video/*,audio/*" ref={upload} onChange={(event) => { uploadFiles(event.target.files); event.target.value = '' }} />
  </aside>
}


