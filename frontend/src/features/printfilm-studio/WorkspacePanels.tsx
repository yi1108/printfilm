import { useEffect, useRef, useState, type ReactNode } from 'react'
import { X, Film, Image as ImageIcon, FileText, Plus, ArrowUpRight } from 'lucide-react'
import { api, type BillingOrder, type UsageChargeRecord, type UsageSummary } from '../../api'
import { dramaApi, type DramaProjectListItem } from '../../api/drama'
import { points } from '../../lib/points'
import { catalogImageModels, catalogVideoModels, useMediaModelsCatalog } from '../../hooks/useMediaModelsCatalog'
import { printfilmStudioApi } from './api'
import { projectSharingApi } from './projectSharing'
import { readNodeDefaults, saveNodeDefaults, readSnapshots, type NodeDefaults } from './workspacePreferences'
import type { CanvasDocument } from './canvas/canvasCodec'
import type { WorkspaceAction } from './WorkspaceChrome'
import { StudioModelSelect } from './StudioModelSelect'

export function WorkspaceDialog({title,children,onClose,kind='standard'}:{title:string;children:ReactNode;onClose:()=>void;kind?:string}) {
  const ref=useRef<HTMLDialogElement>(null)
  useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close()},[])
  return <dialog ref={ref} className={`pf-workspace-dialog is-${kind}`} aria-label={title} onCancel={onClose} onClick={event=>{if(event.target===event.currentTarget)onClose()}}><div className="pf-dialog-inner"><header><h2>{title}</h2><button type="button" aria-label="关闭" onClick={onClose}><X size={20}/></button></header>{children}</div></dialog>
}

export function DefaultModelPanel({onClose}:{onClose:()=>void}) {
  const catalog=useMediaModelsCatalog(), [models,setModels]=useState<{id:string;label:string}[]>([]), [textDefault,setTextDefault]=useState(''), [value,setValue]=useState(readNodeDefaults),[error,setError]=useState('')
  useEffect(()=>{let active=true;void printfilmStudioApi.agentConfig().then(data=>{if(active){setModels(data.models);setTextDefault(data.default_model || data.models[0]?.id || '')}}).catch(()=>{if(active)setError('文字模型加载失败')});return()=>{active=false}},[])
  const groups = [
    {kind:'video' as const,label:'视频',Icon:Film,options:catalogVideoModels(catalog),fallback:catalog?.defaults.video_model || ''},
    {kind:'image' as const,label:'图片',Icon:ImageIcon,options:catalogImageModels(catalog),fallback:catalog?.defaults.image_model || ''},
    {kind:'text' as const,label:'文本',Icon:FileText,options:models,fallback:textDefault},
  ].map(group => ({...group,options:group.options.filter(model=>!('available' in model)||model.available!==false)}))
  const resolved = {...value}
  for (const group of groups) {
    if (group.options.length && !group.options.some(model=>model.id===resolved[group.kind])) resolved[group.kind] = group.options.find(model=>model.id===group.fallback)?.id || group.options[0].id
  }
  const defaultsKey = JSON.stringify(resolved)
  useEffect(()=>{
    const next = JSON.parse(defaultsKey) as NodeDefaults
    if (JSON.stringify(value)===defaultsKey) return
    try { saveNodeDefaults(next);setValue(next) } catch { setError('浏览器无法保存默认模型') }
  },[defaultsKey,value])
  const change=(kind:keyof NodeDefaults,id:string)=>{const next={...value,[kind]:id};try{saveNodeDefaults(next);setValue(next);setError('')}catch{setError('浏览器无法保存偏好，请检查存储设置')}}
  return <WorkspaceDialog title="新建节点的默认模型" onClose={onClose} kind="defaults"><p className="pf-muted">按节点类型分别记住。</p>{groups.map(({kind,label,Icon,options,fallback})=><section className="pf-default-field" key={kind}><div className="pf-default-field-heading"><b><Icon size={19}/>{label}</b><button type="button" className="pf-default-reset" disabled={!options.length} onClick={()=>change(kind,options.find(model=>model.id===fallback)?.id || options[0]?.id || '')}>恢复平台默认</button></div><StudioModelSelect label={`${label}默认模型`} value={resolved[kind]} options={options} onChange={id=>change(kind,id)} large/><small>新建时使用</small></section>)}<footer className="pf-panel-note">已自动保存到此浏览器。</footer>{error&&<p role="alert">{error}</p>}</WorkspaceDialog>
}

export function WalletPanel({balance,onClose,onNavigate}:{balance:string;onClose:()=>void;onNavigate:(path:string)=>void}) {
  const [summary,setSummary]=useState<UsageSummary>(),[items,setItems]=useState<UsageChargeRecord[]>([]),[orders,setOrders]=useState<BillingOrder[]>([]),[tab,setTab]=useState('usage'),[error,setError]=useState(''),[page,setPage]=useState(1),[total,setTotal]=useState(0),[busy,setBusy]=useState(true)
  useEffect(()=>{let active=true;setBusy(true);setError('');void Promise.allSettled([api.usageSummary(),api.usageEvents(page,15),api.listBillingOrders(100)]).then(results=>{if(!active)return;const [a,b,c]=results;if(a.status==='fulfilled')setSummary(a.value);if(b.status==='fulfilled'){setItems(b.value.items);setTotal(b.value.meta.total)}if(c.status==='fulfilled')setOrders(c.value.orders);if(results.some(r=>r.status==='rejected'))setError('部分账单加载失败，请重试');setBusy(false)});return()=>{active=false}},[page])
  return <WorkspaceDialog title="积分钱包" kind="wallet" onClose={onClose}><div className="pf-wallet-card"><span>可用积分</span><div><strong>{summary?points(summary.balance_fen):balance}</strong><button className="pf-primary" onClick={()=>onNavigate('/pricing')}>充值</button></div><footer><button onClick={()=>setTab('orders')}>我的订单</button><button disabled title="当前平台未开放兑换码">兑换码 · 暂未开放</button></footer></div><div className="pf-wallet-stats"><span>本月消耗<b>{points(summary?.charge_fen)}</b></span><span>本月调用<b>{summary?.calls??'—'} 次</b></span><span>冻结积分<b>{points(summary?.frozen_fen)}</b></span></div><div className="pf-panel-tabs">{[['usage','消费记录'],['income','入账记录'],['orders','我的订单']].map(([id,label])=><button key={id} aria-pressed={tab===id} onClick={()=>setTab(id)}>{label}</button>)}</div>{busy?<p>加载账单…</p>:<div className="pf-billing-records">{tab==='usage'?items.map(item=><article key={item.id}><div><b>{item.context||item.billing_label}</b><small>{item.billing_label} · {item.model} · {item.created_at?new Date(item.created_at).toLocaleString():''}</small></div><strong>-{points(item.charge_fen)}</strong></article>):orders.filter(item=>tab==='orders'||item.status==='paid').map(item=><article key={item.out_trade_no}><div><b>{item.sku_name}</b><small>{item.status} · {item.created_at?new Date(item.created_at).toLocaleString():''}</small></div><strong>{tab==='income'?'+':''}{points(item.credit_fen)}</strong></article>)}{(tab==='usage'?!items.length:!orders.filter(o=>tab==='orders'||o.status==='paid').length)&&<p className="pf-muted">暂无记录</p>}</div>}{tab==='usage'&&<div className="pf-pagination"><button disabled={page===1||busy} onClick={()=>setPage(page-1)}>上一页</button><span>{page} / {Math.max(1,Math.ceil(total/15))}</span><button disabled={page*15>=total||busy} onClick={()=>setPage(page+1)}>下一页</button></div>}{error&&<p role="alert">{error}</p>}</WorkspaceDialog>
}

export function WorkspaceUtilityPanel({panel,projectId,title,canvasName,document,writable,onClose,onAction,onNavigate,onRename,onRestore,onSetting,settings}:{panel:WorkspaceAction;projectId:number;title:string;canvasName:string;document:CanvasDocument;writable:boolean;onClose:()=>void;onAction:(action:WorkspaceAction)=>void;onNavigate:(path:string)=>void;onRename:(title:string,canvas:string)=>Promise<void>;onRestore:(document:CanvasDocument)=>void;onSetting:(key:string,value:boolean)=>void;settings:Record<string,boolean>}) {
  const [name,setName]=useState(panel==='newProject'?'':title),[canvas,setCanvas]=useState(canvasName),[projects,setProjects]=useState<Pick<DramaProjectListItem,'id'|'title'>[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[filter,setFilter]=useState('')
  const snapshots=readSnapshots(projectId)
  useEffect(()=>{if(!['projects','canvases'].includes(panel))return;let active=true;setBusy(true);void Promise.all([dramaApi.listProjects({workflow:'canvas',page_size:100}),projectSharingApi.shared()]).then(([result,shared])=>{if(active)setProjects([...result.items,...shared.items.filter(item=>!result.items.some(owned=>owned.id===item.id))])}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setBusy(false)});return()=>{active=false}},[panel])
  const run=async(action:()=>Promise<void>)=>{setBusy(true);setError('');try{await action()}catch(e){setError(e instanceof Error?e.message:'操作失败')}finally{setBusy(false)}}
  const titles:Partial<Record<WorkspaceAction,string>>={project:'项目设置',projects:'切换项目',canvases:'画布管理',versions:'历史版本',newProject:'新建项目',settings:'画布设置',workflow:'任务工作流',help:'新手引导',updates:'近期新功能',account:'账号'}
  const jobs=document.nodes.filter(n=>n.data.taskId||n.data.status)
  return <WorkspaceDialog title={titles[panel]||'工作区'} onClose={onClose}>
    {['project','newProject'].includes(panel)&&<form onSubmit={e=>{e.preventDefault();void run(async()=>{if(panel==='newProject'){const p=await dramaApi.createProject({title:name.trim(),workflow:'canvas'});onNavigate(`/drama/projects/${p.id}/canvas`)}else{await onRename(name.trim(),canvas.trim());onClose()}})}}><label>项目名称<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>{panel==='project'&&<label>画布名称<input required maxLength={80} value={canvas} onChange={e=>setCanvas(e.target.value)}/></label>}<button className="pf-primary" disabled={busy||!name.trim()||!writable}>{busy?'保存中…':panel==='newProject'?'创建项目':'保存设置'}</button></form>}
    {['projects','canvases'].includes(panel)&&<><input aria-label="搜索项目" placeholder="搜索项目" value={filter} onChange={e=>setFilter(e.target.value)}/><div className="pf-project-list">{projects.filter(p=>p.title.includes(filter)).map(p=><button key={p.id} onClick={()=>onNavigate(`/drama/projects/${p.id}/canvas`)}><span>{p.title}</span><small>{p.id===projectId?'当前画布':'打开画布'}</small></button>)}{busy&&<p>加载中…</p>}</div><button className="pf-primary" onClick={()=>onAction('newProject')}><Plus size={16}/>新建项目画布</button><p className="pf-muted">每个项目对应独立画布；支持从更多菜单导入、导出。</p></>}
    {panel==='versions'&&<><p className="pf-muted">此浏览器保留最近 12 个已保存快照。恢复前请确认，当前节点可通过撤销找回。</p>{snapshots.map(s=><article className="pf-version-row" key={s.id}><span>{new Date(s.savedAt).toLocaleString()}<small>版本 {s.version} · {s.document.nodes.length} 个节点</small></span><button disabled={!writable} onClick={()=>{if(window.confirm('恢复此快照？当前画布将替换，可撤销。')){onRestore(s.document);onClose()}}}>恢复</button></article>)}{!snapshots.length&&<p>还没有浏览器快照，下次成功保存后记录。</p>}</>}
    {panel==='settings'&&<>{[['snap','节点吸附网格'],['showEdges','显示连线'],['focusStoryEdges','聚焦参考连线（选中分镜时展开）'],['showMap','显示小地图']].map(([key,label])=><label className="pf-setting-row" key={key}>{label}<input type="checkbox" checked={!!settings[key]} onChange={e=>onSetting(key,e.target.checked)}/></label>)}<button onClick={()=>onAction('tidy')}>按类型整理画布</button></>}
    {panel==='workflow'&&<><p className="pf-muted">当前画布的生成任务，点击记录可前往生成历史查看详情。</p><div className="pf-job-list">{jobs.map(n=><button key={n.id} onClick={()=>onAction('history')}><span>{String(n.data.label||n.type)}<small>{String(n.data.taskId||'尚未提交')}</small></span><b>{({queued:'排队中',running:'生成中',completed:'已完成',succeeded:'已完成',failed:'失败',cancelled:'已取消'} as Record<string,string>)[String(n.data.status)]||String(n.data.status||'待生成')}</b></button>)}{!jobs.length&&<p>当前画布暂无生成任务。</p>}</div></>}
    {panel==='account'&&<><button className="pf-wide-action" onClick={()=>onNavigate('/settings')}>个人资料与账号设置<ArrowUpRight size={16}/></button><button className="pf-wide-action" onClick={()=>onNavigate('/history')}>我的生成记录<ArrowUpRight size={16}/></button><button className="pf-wide-action" onClick={()=>onAction('share')}>项目团队<ArrowUpRight size={16}/></button></>}
    {panel==='help'&&<ol className="pf-guide-list"><li>通过底部“＋”添加文本、图片或视频节点。</li><li>双击文本编辑剧本，使用 Agent 逐步抽取角色、场景和分镜。</li><li>图片与提示词连接视频节点，生成前确认模型、参数和费用。</li><li>顶部切换故事板查看素材；Shift+F 搜索节点，Ctrl+Z 撤销。</li><li>画布自动保存；更多菜单支持导出备份和浏览器历史快照。</li></ol>}
    {panel==='updates'&&<ul className="pf-guide-list"><li>图片、分镜、提示词、视频独立分区。</li><li>分镜视频读取实时文本与对应角色、场景图片。</li><li>图片草稿显示提示词，长内容在卡片内滚动。</li><li>顶部模型偏好、生成历史、项目分享与账单入口。</li></ul>}
    {error&&<p role="alert">{error}</p>}
  </WorkspaceDialog>
}
