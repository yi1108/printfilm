import { useState } from 'react'
import { ArrowRight, CheckCircle2, ChevronDown, ChevronUp, Circle, CircleDot, ListChecks } from 'lucide-react'
import { storyGuide, storyImageState, storyNodeLabel, type StoryNode, type StoryStage, type StoryEdge } from './storyWorkflow'

export function StoryGuide({ nodes, edges, preferredIds, writable, onStage, onRepair, onGenerate, running = false, pending = false }: {
  nodes: StoryNode[]; edges: StoryEdge[]; preferredIds: string[]; writable: boolean; running?: boolean; pending?: boolean
  onStage: (stage: StoryStage, script: StoryNode, assets: StoryNode[]) => void
  onRepair: (scriptId: string) => void
  onGenerate: (id: string, kind: 'image' | 'video') => void
}) {
  const [scriptId, setScriptId] = useState(''), [collapsed, setCollapsed] = useState(false)
  const guide = storyGuide(nodes, scriptId ? [scriptId] : preferredIds, edges)
  if (!guide.script) return pending || running ? <section className="pf-story-plan" aria-label="剧本创作计划"><div className="pf-story-plan-heading"><ListChecks size={17} /><b>先完成故事剧本，再准备参考素材和分镜</b><span>0 / 3</span></div><ol>{['撰写故事剧本', '建立角色与场景参考素材', '规划分镜视频'].map((label, index) => <li key={label}>{index === 0 ? <CircleDot size={17} /> : <Circle size={17} />}<span>{label}</span></li>)}</ol><button className="pf-story-continue" disabled><ArrowRight size={17} />{pending ? '先应用这批剧本改动，再继续下一步' : '正在规划故事剧本…'}</button></section> : null
  const script = guide.script
  const pairedInGroup = (node: StoryNode) => {
    const group = nodes.find((item) => item.id === node.parentId && item.type === 'group' && item.data.sourceScriptId === script.id && item.data.storyKind === `${String(node.data.storyKind)}_group`)
    const writer = nodes.find((item) => item.id === node.data.promptNodeId)
    return !!group && !!writer && writer.data.sourceScriptId === script.id && node.parentId === group.id && writer.parentId === group.id && edges.some((edge) => edge.source === writer.id && edge.target === node.id)
  }
  const assetGroupingMissing = guide.assets.some((node) => !pairedInGroup(node))
  const shotGroupingMissing = guide.shotPlans.some((shot) => shot.video && !pairedInGroup(shot.video))
  const groupingMissing = assetGroupingMissing || shotGroupingMissing
  const graphReady = guide.graphReady && !shotGroupingMissing
  const complete = 1 + Number(guide.assetsReady && !assetGroupingMissing) + Number(graphReady)
  const stage = !guide.assetsReady || assetGroupingMissing ? 'assets' : 'shots'
  const title = stage === 'assets' ? `从《${storyNodeLabel(script)}》提取角色和场景，建立参考素材` : graphReady ? '分组与分镜已就绪，按需运行节点生成素材' : '根据角色和场景参考，规划分镜视频'
  const next = () => {
    if (groupingMissing && guide.assets.length && !guide.missingCharacters.length || guide.needsRepair && !guide.missingCharacters.length) onRepair(script.id)
    else onStage(stage, script, guide.assets)
  }
  const steps = [{ label: '撰写故事剧本', done: true, role: '原创剧本' }, { label: '建立角色与场景参考素材', done: guide.assetsReady && !assetGroupingMissing, role: '' }, { label: '规划分镜视频', done: graphReady, role: '导演执导' }]
  return <section className="pf-story-plan" aria-label="剧本创作计划">
    <button className="pf-story-plan-heading" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}><ListChecks size={17} /><b title={title}>{title}</b><span>{complete} / 3</span>{collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</button>
    {!collapsed && <>
      {guide.scripts.length > 1 && <select aria-label="选择引导剧本" value={script.id} onChange={(event) => setScriptId(event.target.value)}>{guide.scripts.map((item) => <option key={item.id} value={item.id}>{storyNodeLabel(item)}</option>)}</select>}
      <ol>{steps.map((step, index) => <li key={step.label} className={step.done ? 'is-done' : index === complete ? 'is-current' : ''}>{step.done ? <CheckCircle2 size={17} /> : index === complete ? <CircleDot size={17} /> : <Circle size={17} />}<span>{step.label}</span><small>{step.role}</small></li>)}</ol>
      {!guide.graphReady || groupingMissing ? <button className="pf-story-continue" disabled={!writable || running || pending} onClick={next}><ArrowRight size={17} />{pending ? '先处理这批改动，再继续下一步' : running ? '正在规划，请稍候…' : `继续：${stage === 'assets' ? '建立角色与场景参考素材' : '规划分镜视频'}`}</button> : <div className="pf-story-plan-done">已完成规划 · 素材生成进度见下方改动卡片</div>}
      {!!guide.assets.length && <details className="pf-story-existing"><summary>已有素材与分镜（{guide.assets.length + guide.shotPlans.length}）</summary><div>{guide.assets.map((node) => <button key={node.id} disabled={!writable || running || storyImageState(node) === 'running'} onClick={() => onGenerate(node.id, 'image')}>{storyNodeLabel(node)} · {storyImageState(node) === 'completed' ? '已生成' : '运行到图片'}</button>)}{guide.shotPlans.map((shot) => <button key={shot.id} disabled={!writable || running || !!shot.missingLinks.length} title={[...shot.missingLinks, ...shot.missingReferences].join('、')} onClick={() => { if (shot.video) onGenerate(shot.video.id, 'video') }}>{shot.label} · 运行到视频</button>)}</div></details>}
    </>}
  </section>
}
