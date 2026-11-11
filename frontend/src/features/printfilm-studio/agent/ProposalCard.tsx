import { useState } from 'react'
import { CheckSquare, ChevronRight, Group, Link2, LoaderCircle, Pencil, Play, Plus, Undo2 } from 'lucide-react'
import { proposalMedia, proposalStatus, type AgentProposal, type ProposalAction, type ProposalStates } from './proposals'
import { storyImageState, type StoryNode } from './storyWorkflow'

export type ProposalControls = { nodes: StoryNode[]; states: ProposalStates; writable: boolean; busy: boolean; onAction: (proposal: AgentProposal, action: ProposalAction) => Promise<void>; onRun: (ids: string[]) => void }
export function ProposalCard({ proposal, controls }: { proposal: AgentProposal; controls: ProposalControls }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const status = proposalStatus(proposal, controls.states, controls.nodes)
  const applied = status === 'applied'
  const media = proposalMedia(proposal)
  // The planner also records completion manifests on the source script. Those
  // bookkeeping fields are not a rewritten script or another generation task.
  const withoutManifest = (node: NonNullable<AgentProposal['nodes'][number]['after']>) => ({ ...node, data: Object.fromEntries(Object.entries(node.data).filter(([key]) => !['storyAssetsReady', 'storyShotsReady', 'storyCharacterNames', 'storySceneNames'].includes(key))) })
  const visibleChanges = proposal.nodes.filter(({ before, after }) => !before || !after || before.type !== 'script' || JSON.stringify(withoutManifest(before)) !== JSON.stringify(withoutManifest(after)))
  const changed = visibleChanges.flatMap((change) => change.after ? [change.after] : [])
  const groups = changed.filter((node) => node.type === 'group')
  const text = changed.filter((node) => ['text', 'script'].includes(node.type))
  const memberOrder = groups.flatMap((group) => Array.isArray(group.data.children) ? group.data.children.map(String) : [])
  const ordered = [...visibleChanges].sort((a, b) => (memberOrder.indexOf(a.id) < 0 ? 9999 : memberOrder.indexOf(a.id)) - (memberOrder.indexOf(b.id) < 0 ? 9999 : memberOrder.indexOf(b.id)))
  const actual = media.map((node) => controls.nodes.find((item) => item.id === node.id)).filter((node): node is StoryNode => !!node)
  const complete = actual.filter((node) => storyImageState(node) === 'completed').length
  const active = actual.some((node) => storyImageState(node) === 'running')
  const action = async (value: ProposalAction, run = false) => {
    setBusy(true); setError('')
    try { await controls.onAction(proposal, value); if (run) controls.onRun(media.map((node) => node.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') }
    finally { setBusy(false) }
  }
  const label = (id: string) => String(changed.find((node) => node.id === id)?.data.label || controls.nodes.find((node) => node.id === id)?.data.label || '节点')
  return <section className={`pf-agent-proposal is-${status}`} aria-label="节点改动方案">
    <div className="pf-proposal-changes">{ordered.filter((item) => item.after?.type !== 'group').map((change) => <div key={change.id}>{change.before ? <Pencil size={16} /> : <Plus size={16} />}<span>{!change.after ? '删除' : change.before ? '修改' : '新建'}{change.after && ['text', 'script'].includes(change.after.type) ? '文本' : change.after?.type === 'videoGeneration' ? '视频' : change.after && ['character', 'scene', 'image', 'imageGeneration'].includes(change.after.type) ? '图片' : '节点'}「{String((change.after || change.before)?.data.label || '未命名')}」</span></div>)}
      {proposal.edges.map((change) => { const edge = change.after || change.before!; return <div key={change.id}><Link2 size={16} /><span>{change.after ? '连接' : '断开'} {label(edge.source)} → {label(edge.target)}</span></div> })}
      {groups.map((group) => <div key={group.id}><Group size={16} /><span>把 {Array.isArray(group.data.children) ? group.data.children.length : 0} 个节点收进分组「{String(group.data.label)}」</span></div>)}
    </div>
    {!!text.length && <details className="pf-proposal-prompts"><summary><ChevronRight size={14} />看写作要求（{text.length}）</summary>{text.map((node) => <article key={node.id}><b>{String(node.data.label)}</b><p>{String(node.data.writingPrompt || node.data.text || node.data.prompt || '')}</p></article>)}</details>}
    <div className="pf-proposal-summary"><b>{changed.filter((node) => node.type !== 'group').length} 个节点</b><span>文本 {text.length} · 图片 {media.filter((node) => !node.type.includes('video')).length} · 视频 {media.filter((node) => node.type.includes('video')).length}</span><small>{media.length ? '运行前选择模型并确认费用' : '应用到画布后可继续下一步'}</small></div>
    <div className="pf-proposal-actions">
      {applied ? <><span><CheckSquare size={15} />已应用</span><button disabled={busy || controls.busy || !controls.writable || active} onClick={() => void action('undo')}><Undo2 size={15} />撤销</button>{!!media.length && <button disabled={busy || controls.busy || !controls.writable || active || complete === media.length} onClick={() => controls.onRun(media.map((node) => node.id))}><Play size={15} />{active ? '正在运行这一组…' : complete === media.length ? '已完成' : '运行这组节点'}</button>}</> : status === 'ignored' ? <span>已忽略这批改动</span> : <>
        {!!media.length && <button className="is-primary" disabled={busy || controls.busy || !controls.writable} onClick={() => void action('apply', true)}><Play size={15} />应用并运行</button>}
        <button disabled={busy || controls.busy || !controls.writable} onClick={() => void action('apply')}><CheckSquare size={15} />只应用</button><button disabled={busy || controls.busy || !controls.writable} onClick={() => void action('ignore')}>忽略</button>
      </>}
    </div>
    {applied && !!media.length && <div className="pf-proposal-progress"><b>{active && <LoaderCircle size={15} className="pf-agent-progress-spinner" />}{active ? '运行中' : '生成进度'} · 已完成 {complete} / {media.length}</b>{actual.map((node) => <div key={node.id}><span>{String(node.data.label)}</span><small>{{ pending: '待生成', running: '生成中', completed: '已完成', failed: '失败，可重试' }[storyImageState(node)]}</small></div>)}</div>}
    {error && <p role="alert">{error}</p>}
  </section>
}
