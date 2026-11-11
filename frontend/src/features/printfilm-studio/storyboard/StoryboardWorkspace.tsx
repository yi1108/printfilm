import { WorkspaceToolbar } from '../WorkspaceToolbar'
import { lazy, Suspense, useContext, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, AudioLines, Bot, ChevronLeft, ChevronRight, Download, Eye, FileText, Film, FolderOpen, Image as ImageIcon, MessageSquarePlus, MoreHorizontal, Pause, Pencil, Play, Plus, Redo2, Scan, Scissors, Undo2, X } from 'lucide-react'
import { StudioComposerContext, StudioNodeActionsContext } from '../canvas/studioNodeContext'
import { PromptComposer } from '../canvas/PromptComposer'
import { nodeMediaKind } from '../canvas/nodeOperations'
import { nodeDraft } from '../canvas/nodeDraft'
import { collectMediaUrls } from '../canvas/imageVariants'
import { WorkspaceDialog } from '../WorkspacePanels'
import { storyDuration, storyKinds, storyLabels, storyMedia, storySequence, storyStatus, storyTitle, type StoryKind, type StoryNode } from './storyboardState'
import './storyboard.css'

const TextEditor = lazy(() => import('../canvas/TextNodeEditor').then(module => ({ default: module.TextNodeEditor })))
const icons = { audio: AudioLines, text: FileText, image: ImageIcon, video: Film }
type Props = {
  nodes: StoryNode[]; selectedId: string | null; onSelect: (id: string | null) => void
  onAdd: (kind: StoryKind) => StoryNode | null | undefined; onLocate: (id: string) => void
  onSequence: (ids: string[]) => void; onDuration: (id: string, seconds: number) => void
  onCompose: (ids: string[]) => void; onSave: () => void
  onUndo: () => void; onRedo: () => void; canUndo: boolean; canRedo: boolean; onAssets: () => void; onAgent: () => void
}

export function StoryboardWorkspace({ nodes, selectedId, onSelect, onAdd, onLocate, onSequence, onDuration, onCompose, onSave, onUndo, onRedo, canUndo, canRedo, onAssets, onAgent }: Props) {
  const actions = useContext(StudioNodeActionsContext)!
  const composer = useContext(StudioComposerContext)
  const [category, setCategory] = useState<StoryKind | 'all'>('all')
  const [detailId, setDetailId] = useState<string | null>(null)
  const [menu, setMenu] = useState(false), [rename, setRename] = useState(false), [name, setName] = useState('')
  const [sequenceOpen, setSequenceOpen] = useState(false), [preview, setPreview] = useState(false)
  const [audioMenu, setAudioMenu] = useState(false), [soundtrack, setSoundtrack] = useState('')
  const [notice, setNotice] = useState('')
  const [addMenu, setAddMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const allowed = nodes.filter(node => node.type !== 'group' && !['recipe','director3d','frameAnalysis','task_flow','director_flow'].includes(String(node.type)))
  const selected = allowed.find(node => node.id === detailId)
  const kind = selected ? nodeMediaKind(selected) : null
  const sequence = storySequence(nodes)
  const writable = !!actions.writable
  const busy = !!selected && (actions.submittingNodeIds?.has(selected.id) || /排队|生成中/.test(storyStatus(selected)))
  const soundtracks = allowed.filter(node => nodeMediaKind(node) === 'audio' && storyMedia(node))

  const choose = (node: StoryNode) => {
    setCategory(nodeMediaKind(node)); setDetailId(node.id); setMenu(false); setRename(false); onSelect(node.id)
  }
  // New results created by image editing/video actions become the active detail.
  useEffect(() => {
    if (!detailId || !selectedId || selectedId === detailId) return
    const node = allowed.find(item => item.id === selectedId)
    if (node) { setDetailId(node.id); setCategory(nodeMediaKind(node)); setMenu(false) }
  }, [selectedId])
  useEffect(() => { if (detailId && !selected) setDetailId(null) }, [detailId, selected])
  useEffect(() => {
    if (!menu) return
    const close = (event: PointerEvent) => { if (!menuRef.current?.contains(event.target as Node)) setMenu(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenu(false) }
    document.addEventListener('pointerdown', close); document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', escape) }
  }, [menu])

  const add = (type: StoryKind) => { const node = onAdd(type); if (node) choose(node) }
  const openCategory = (value: StoryKind | 'all') => { setCategory(value); setDetailId(null); setMenu(false); onSelect(null) }
  const addToSequence = (node: StoryNode) => { onSequence([...sequence.map(item => item.id), node.id]); setSequenceOpen(true) }
  const card = (node: StoryNode) => {
    const type = nodeMediaKind(node), Icon = icons[type], media = storyMedia(node)
    const state = storyStatus(node, actions.submittingNodeIds?.has(node.id))
    return <button type="button" key={node.id} className={`pf-board-card${node.id === detailId ? ' is-active' : ''}`} aria-label={`打开${storyTitle(node)}`} aria-pressed={node.id === detailId} onClick={() => choose(node)}>
      <span className="pf-board-card-title">{storyTitle(node)}</span>
      <span className={`pf-board-thumb is-${type}`}>{type === 'text' ? <span>{nodeDraft(node) || '点击编写内容'}</span> : media && type === 'image' ? <img src={media} alt="" loading="lazy"/> : media && type === 'video' ? <video src={media} preload="metadata" muted/> : <><Icon size={30}/><small>{state}</small></>}</span>
      <small>{type === 'image' && node.data.naturalWidth ? `图片 · ${node.data.naturalWidth} × ${node.data.naturalHeight}` : String(node.data.modelId || node.data.writingModel || storyLabels[type])}</small><small>{state}</small>
    </button>
  }
  const section = (type: StoryKind, sidebar = false) => {
    const Icon = icons[type], items = allowed.filter(node => nodeMediaKind(node) === type)
    return <section key={type} className={`pf-board-section is-${type}${sidebar ? ' is-sidebar' : ''}`} aria-label={`${storyLabels[type]}列表`}>
      <header><span><Icon size={18}/><b>{storyLabels[type]}</b><small>{items.length}</small></span><span><button aria-label={`展开${storyLabels[type]}列表`} onClick={() => openCategory(category === type && !detailId ? 'all' : type)}><Scan size={17}/></button><button disabled={!writable} aria-label={`添加${storyLabels[type]}`} onClick={() => add(type)}><Plus size={18}/></button></span></header>
      <div className="pf-board-items">{items.length ? items.map(card) : <div className="pf-board-empty">暂无{storyLabels[type]}<button disabled={!writable} onClick={() => add(type)}>添加{storyLabels[type]}</button></div>}</div>
    </section>
  }

  return <section className="pf-board-workspace" aria-label="故事板工作区">
    <nav className="pf-board-tabs" aria-label="故事板分类"><button aria-pressed={category === 'all'} onClick={() => openCategory('all')}>全部</button>{storyKinds.map(type => <button key={type} aria-pressed={category === type} onClick={() => openCategory(type)}>{storyLabels[type]}</button>)}</nav>
    <div className={`pf-board-layout${selected ? ' has-detail' : category === 'all' ? ' is-overview' : ' is-category'}`}>
      {selected && kind ? <>{section(kind, true)}<section className="pf-board-detail" aria-label="素材详情">
        <header><button aria-label="返回分类网格" onClick={() => { setDetailId(null); onSelect(null) }}><ArrowLeft size={19}/></button><b>{storyTitle(selected)}</b><span/><button onClick={() => onLocate(selected.id)}>在画布中查看</button><button aria-label="向助手提问" onClick={() => actions.ask(selected.id)}><MessageSquarePlus size={19}/></button></header>
        <div className="pf-board-detail-scroll">
          <div className="pf-board-node-heading">{(() => { const Icon = icons[kind]; return <Icon size={17}/> })()}{rename ? <form onSubmit={event => { event.preventDefault(); if (name.trim()) actions.rename(selected.id, name.trim()); setRename(false) }}><input aria-label="素材名称" autoFocus maxLength={200} value={name} onChange={event => setName(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') setRename(false) }}/><button>保存</button></form> : <b>{storyTitle(selected)}</b>}<span className={busy ? 'is-busy' : ''} role="status">{storyStatus(selected, actions.submittingNodeIds?.has(selected.id))}</span><div className="pf-board-menu-host" ref={menuRef}><button aria-label="素材操作" aria-expanded={menu} onClick={() => setMenu(!menu)}><MoreHorizontal size={19}/></button>{menu && <div className="pf-board-menu">{[
            { label: '重命名', run: () => { setName(storyTitle(selected)); setRename(true) }, edit: true },
            { label: '复制节点', run: () => actions.duplicate(selected.id), edit: true },
            { label: '替换素材', run: () => actions.upload(selected.id), edit: true, hide: kind === 'text' },
            { label: '生成历史', run: () => actions.history(selected.id), hide: kind === 'text' },
            { label: '下载', run: () => actions.download(selected.id) },
            { label: '删除节点', run: () => actions.remove(selected.id), edit: true },
          ].filter(item => !item.hide).map(item => <button disabled={item.edit && (!writable || busy)} key={item.label} onClick={() => { item.run(); setMenu(false) }}>{item.label}</button>)}</div>}</div></div>
          {kind !== 'text' && storyMedia(selected) && <div className="pf-board-media-tools">
            {kind === 'image' ? <><button disabled={!writable || busy} onClick={() => actions.openComposer(selected.id, 'edit')}><Pencil size={16}/>编辑图片</button><button disabled={!writable || busy} onClick={() => actions.openComposer(selected.id, 'crop')}><Scissors size={16}/>裁剪</button><button disabled={!writable} onClick={() => actions.openComposer(selected.id, 'video')}><Film size={16}/>图生视频</button><button disabled={!writable} onClick={() => actions.openComposer(selected.id, 'reference')}><Film size={16}/>参考生成视频</button></> : <><button disabled={!writable || busy} onClick={() => actions.mediaEdit(selected.id, 'trim')}><Scissors size={16}/>裁剪{storyLabels[kind]}</button>{kind === 'video' && <button disabled={!writable} onClick={() => actions.mediaEdit(selected.id, 'extract_audio')}><AudioLines size={16}/>提取音频</button>}<button disabled={!writable || busy} onClick={() => onSelect(selected.id)}><Pencil size={16}/>生成设置</button></>}
            <button aria-label="下载素材" onClick={() => actions.download(selected.id)}><Download size={16}/></button><button aria-label="预览素材" onClick={() => actions.preview(selected.id)}><Eye size={16}/></button>{['image','video'].includes(kind) && <button disabled={!writable || sequence.some(node => node.id === selected.id)} onClick={() => addToSequence(selected)}><Plus size={16}/>加入分镜</button>}
          </div>}
          {kind === 'text' ? <>
            {busy && <div className="pf-board-progress" role="status">AI 正在写…<progress aria-label="AI 写作进行中"/></div>}
            <Suspense fallback={<p>加载文本编辑器…</p>}><TextEditor references={actions.writingReferences?.(selected.id)} key={selected.id} embedded draft={{label:storyTitle(selected),text:nodeDraft(selected),prompt:String(selected.data.prompt||''),clipStart:'',clipEnd:''}} writable={writable && !busy} onChange={draft => actions.updateText(selected.id, draft.text)} onSave={onSave} onClose={() => {}}/></Suspense>
            <div className="pf-board-writing-tabs"><button aria-pressed={actions.textComposer?.nodeId !== selected.id} disabled={busy} onClick={() => actions.closeTextComposer?.()}>自己写</button><button aria-pressed={actions.textComposer?.nodeId === selected.id} onClick={() => actions.generateText(selected.id)}>AI 写</button></div>
            {actions.textComposer?.nodeId === selected.id && actions.textComposer.content}
          </> : <>
            <div className={`pf-board-stage${storyMedia(selected) ? ' has-media' : ''}`}>
              {storyMedia(selected) ? kind === 'image' ? <img src={storyMedia(selected)} alt={storyTitle(selected)}/> : kind === 'video' ? <video key={storyMedia(selected)} src={storyMedia(selected)} controls preload="metadata"/> : <audio key={storyMedia(selected)} src={storyMedia(selected)} controls/> : busy ? <div className="pf-board-progress" role="status">{storyStatus(selected, actions.submittingNodeIds?.has(selected.id))}<progress aria-label="生成进行中"/></div> : kind === 'audio' ? <div className="pf-board-audio-start"><small>尝试：</small><button disabled={!writable} onClick={() => onSelect(selected.id)}>配音</button><button disabled={!writable} onClick={() => {setNotice('上传音效文件后可预览、剪辑并用于分镜配音。');actions.upload(selected.id)}}>上传音效</button><button disabled={!writable} onClick={() => {setNotice('上传配乐文件后可选作连续预览的背景音。');actions.upload(selected.id)}}>上传配乐</button></div> : (() => { const Icon = icons[kind]; return <Icon size={44}/> })()}
            </div>
            {selected.data.error ? <p role="alert">{String(selected.data.error)}</p> : null}
            {collectMediaUrls(selected.data).length > 1 && <div className="pf-board-variants">{collectMediaUrls(selected.data).map((url,index) => <button key={url} aria-label={`查看第 ${index+1} 张`} aria-pressed={Number(selected.data.mediaIndex || 0) === index} onClick={() => actions.setMediaIndex(selected.id,index)}><img src={url} alt=""/></button>)}<button onClick={() => actions.compareVariants(selected.id)}>对比</button><button disabled={!writable} onClick={() => actions.splitVariants(selected.id)}>拆为节点</button></div>}
            {composer?.nodeId === selected.id && <fieldset className="pf-board-composer" disabled={!writable || busy} inert={!writable || busy}><PromptComposer key={selected.id} {...composer} attached/></fieldset>}
          </>}
        </div>
      </section></> : category === 'all' ? <><div className="pf-board-left-stack">{section('audio')}{section('text')}</div>{section('image')}{section('video')}</> : section(category)}
    </div>
    <section className={`pf-board-sequence${sequenceOpen ? ' is-open' : ''}`} aria-label="分镜序列">
      <header><button aria-expanded={sequenceOpen} onClick={() => setSequenceOpen(!sequenceOpen)}><Film size={17}/><b>分镜</b><small>{sequence.length} 镜 · {sequence.reduce((sum,node) => sum + storyDuration(node),0).toFixed(2)} 秒</small></button><span/>
        <button aria-label="连续预览" disabled={!sequence.length || sequence.some(node => !storyMedia(node))} onClick={() => setPreview(true)}><Play size={17}/></button>
        <button aria-label="分镜配音" aria-expanded={audioMenu} onClick={() => setAudioMenu(!audioMenu)}><AudioLines size={17}/></button>
        <button aria-label="剪辑合成分镜" disabled={!writable || sequence.length < 2 || sequence.some(node => nodeMediaKind(node) !== 'video' || !storyMedia(node))} title="将两个以上已生成视频按分镜顺序合成" onClick={() => onCompose(sequence.map(node => node.id))}><Scissors size={17}/></button>
        <button disabled={!writable || !sequence.length} onClick={() => onSequence([])}>清空</button>
      </header>
      {audioMenu && <div className="pf-board-soundtrack"><label>预览背景音<select aria-label="预览背景音" value={soundtrack} onChange={event => setSoundtrack(event.target.value)}><option value="">无</option>{soundtracks.map(node => <option key={node.id} value={node.id}>{storyTitle(node)}</option>)}</select></label><button disabled={!writable} onClick={() => add('audio')}>添加配音</button></div>}
      {sequenceOpen && <div className="pf-board-sequence-items">{sequence.map((node,index) => <div key={node.id} className="pf-board-shot"><button onClick={() => choose(node)}>{index+1}. {storyTitle(node)}</button><label>秒<input aria-label={`${storyTitle(node)}停留秒数`} type="number" min={0.1} max={600} step={0.1} disabled={!writable || nodeMediaKind(node) !== 'image'} value={storyDuration(node) || ''} onChange={event => {const value=Number(event.target.value);if(value>0 && value<=600)onDuration(node.id,value)}}/></label><button aria-label="分镜前移" disabled={!writable || index===0} onClick={() => {const ids=sequence.map(n=>n.id);[ids[index-1],ids[index]]=[ids[index],ids[index-1]];onSequence(ids)}}><ChevronLeft size={15}/></button><button aria-label="分镜后移" disabled={!writable || index===sequence.length-1} onClick={() => {const ids=sequence.map(n=>n.id);[ids[index+1],ids[index]]=[ids[index],ids[index+1]];onSequence(ids)}}><ChevronRight size={15}/></button><button aria-label="移出分镜" disabled={!writable} onClick={() => onSequence(sequence.filter(n=>n.id!==node.id).map(n=>n.id))}><X size={15}/></button></div>)}<button disabled={!writable} onClick={() => {onSequence([...sequence.map(n=>n.id),...allowed.filter(n=>['image','video'].includes(nodeMediaKind(n)) && storyMedia(n)).map(n=>n.id)]);setSequenceOpen(true)}}><Plus size={16}/>加入已就绪素材</button></div>}
    </section>
    <footer className="pf-board-dock-row"><button onClick={onAssets}><FolderOpen size={17}/>素材管理</button><WorkspaceToolbar label="故事板操作条"><div className="pf-board-add"><button className="pf-toolbar-primary" aria-label="添加故事板素材" aria-expanded={addMenu} disabled={!writable} onClick={()=>setAddMenu(!addMenu)}><Plus size={23}/></button>{addMenu&&<div>{storyKinds.map(type=><button key={type} onClick={()=>{add(type);setAddMenu(false)}}>{storyLabels[type]}</button>)}</div>}</div><button aria-label="预览分镜" disabled={!sequence.length || sequence.some(node=>!storyMedia(node))} onClick={()=>setPreview(true)}><Play size={19}/></button><button aria-label="展开分镜条" aria-pressed={sequenceOpen} onClick={()=>setSequenceOpen(!sequenceOpen)}><Film size={19}/></button><button aria-label="撤销" disabled={!writable||!canUndo} onClick={onUndo}><Undo2 size={19}/></button><button aria-label="重做" disabled={!writable||!canRedo} onClick={onRedo}><Redo2 size={19}/></button><button aria-label="故事板助手" onClick={onAgent}><Bot size={21}/></button></WorkspaceToolbar><span/></footer>
    {notice && <p className="pf-board-notice" role="status">{notice}<button aria-label="关闭提示" onClick={()=>setNotice('')}><X size={14}/></button></p>}
    {preview && <SequencePreview nodes={sequence} soundtrack={storyMedia(soundtracks.find(n=>n.id===soundtrack) || {id:'',position:{x:0,y:0},data:{}})} onClose={()=>setPreview(false)}/>}
  </section>
}

function SequencePreview({nodes,soundtrack,onClose}:{nodes:StoryNode[];soundtrack:string;onClose:()=>void}) {
  const [index,setIndex]=useState(0),[playing,setPlaying]=useState(true),[error,setError]=useState('')
  const video=useRef<HTMLVideoElement>(null),audio=useRef<HTMLAudioElement>(null)
  const node=nodes[index],kind=nodeMediaKind(node)
  useEffect(()=>{if(!nodes.length)onClose();else if(index>=nodes.length)setIndex(nodes.length-1)},[nodes.length,index])
  const next=()=>{if(index<nodes.length-1)setIndex(index+1);else setPlaying(false)}
  useEffect(()=>{if(!playing || kind!=='image')return;const timer=window.setTimeout(next,(storyDuration(node)||3)*1000);return()=>clearTimeout(timer)},[index,playing,kind])
  useEffect(()=>{const media=video.current;if(!media)return;if(playing)void media.play().catch(()=>{setPlaying(false);setError('点击播放开始预览')});else media.pause()},[index,playing])
  useEffect(()=>{const media=audio.current;if(!media)return;if(playing)void media.play().catch(()=>setError('背景音未能播放，请重新点击播放'));else media.pause()},[playing])
  if (!node) return null
  return <WorkspaceDialog title="分镜连续预览" kind="sequence" onClose={onClose}><div className="pf-board-preview-stage">{kind==='image'?<img src={storyMedia(node)} alt={storyTitle(node)}/>:<video key={node.id} ref={video} src={storyMedia(node)} controls onEnded={next} onPlay={()=>setPlaying(true)} onPause={event=>{if(!event.currentTarget.ended)setPlaying(false)}} onError={()=>{setPlaying(false);setError('此片段加载失败，可跳到下一镜')}}/>}</div>{soundtrack&&<audio ref={audio} src={soundtrack} loop/>}<footer className="pf-board-playback"><button aria-label="上一镜" disabled={index===0} onClick={()=>setIndex(index-1)}><ArrowLeft size={18}/></button><button aria-label={playing?'暂停预览':'播放预览'} onClick={()=>{setError('');setPlaying(!playing)}}>{playing?<Pause size={18}/>:<Play size={18}/>}</button><span>{index+1} / {nodes.length} · {storyTitle(node)}</span><button aria-label="下一镜" disabled={index===nodes.length-1} onClick={()=>setIndex(index+1)}><ArrowRight size={18}/></button></footer>{error&&<p role="status">{error}</p>}</WorkspaceDialog>
}
