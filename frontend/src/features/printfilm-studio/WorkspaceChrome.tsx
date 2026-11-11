import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Download, Film, FolderPlus, History, House, Link2, MoreHorizontal, Search, Settings2, UserRound, Workflow, Palette, FolderOpen, CircleHelp, Sparkles, AudioLines } from 'lucide-react'
export type WorkspaceMode = 'canvas' | 'document' | 'storyboard'
export type WorkspaceAction = 'home' | 'episodes' | 'agent' | 'assets' | 'history' | 'download' | 'share' | 'save' | 'more' | 'pricing' | 'account' | 'tidy' | 'defaults' | 'search' | 'workflow' | 'recipes' | 'settings' | 'help' | 'updates' | 'project' | 'projects' | 'versions' | 'canvases' | 'newProject' | 'records' | 'video' | 'audio' | 'theme' | 'import' | 'wallet'
export function WorkspaceChrome({ title, status, balance, mode, dockWidth, onMode, onAction }: {
  title: string; status: string; balance: string; mode: WorkspaceMode; dockWidth: number; onMode: (mode: WorkspaceMode) => void; onAction: (action: WorkspaceAction) => void
}) {
  const [menu, setMenu] = useState(false), root = useRef<HTMLElement>(null)
  useEffect(() => { if (!menu) return; const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setMenu(false) }; const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenu(false) }; document.addEventListener('pointerdown', close); document.addEventListener('keydown', key); return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', key) } }, [menu])
  const action = (value: WorkspaceAction) => { setMenu(false); onAction(value) }
  const entries = [
    ['search', '搜索节点', Search], ['workflow', '任务工作流', Workflow], ['recipes', '我的配方', Workflow], ['settings', '画布设置', Settings2], ['help', '新手引导', CircleHelp], ['updates', '近期新功能', Sparkles], ['project', '项目设置', Settings2], ['versions', '历史版本', History], ['canvases', '画布管理', FolderOpen], ['newProject', '新建项目', FolderPlus], ['download', '导出画布包…', Download], ['import', '导入画布包…', Download], ['records', '查看成片记录', Film], ['video', '视频生成面板', Film], ['audio', '音频合成室', AudioLines], ['theme', '切换主题', Palette],
  ] as const
  return <header ref={root} className="pf-workspace-chrome pf-chrome-v2" style={{ right: dockWidth + 16 }}>
    <div className="pf-chrome-breadcrumb"><button className="pf-top-box pf-home" aria-label="返回项目列表" title="返回项目列表" onClick={() => action('home')}><House size={20}/></button><button className="pf-title-control" onClick={() => action('projects')}><b>{title}</b><ChevronDown size={15}/></button><button className={`pf-save-state ${/待保存|未保存|失败|冲突/.test(status) ? 'is-pending' : ''}`} title={status} onClick={() => action('save')} role="status">{status}</button></div>
    <div className="pf-top-right"><nav className="pf-top-box pf-view-tabs" aria-label="工作区视图"><button aria-pressed={mode === 'canvas'} onClick={() => onMode('canvas')}>画布</button><button aria-pressed={mode === 'storyboard'} onClick={() => onMode('storyboard')}>故事板</button></nav>
    <button className="pf-top-box pf-default-trigger" onClick={() => action('defaults')}><Settings2 size={18}/><span>默认模型</span><ChevronDown size={14}/></button>
    <div className="pf-top-box pf-top-tools"><button aria-label="搜索节点" title="搜索节点 · Shift+F" onClick={() => action('search')}><Search size={21}/></button><button aria-label="任务工作流" title="任务工作流" onClick={() => action('workflow')}><Workflow size={20}/></button><button aria-label="导出画布包" title="导出画布包" onClick={() => action('download')}><Download size={20}/></button><button aria-label="生成历史" title="生成历史" onClick={() => action('history')}><History size={20}/></button><button aria-label="更多菜单" title="更多" aria-expanded={menu} onClick={() => setMenu(!menu)}><MoreHorizontal size={20}/></button></div>
    <button className="pf-top-box" aria-label="操作指引" title="操作指引 · 分步高亮教学" onClick={() => action('help')}><CircleHelp size={18}/><span>操作指引</span></button>
    <button className="pf-top-box pf-share-trigger" onClick={() => action('share')}><Link2 size={17}/>分享</button><button className="pf-top-box" onClick={() => action('wallet')}>积分余额 <b>{balance}</b><ChevronDown size={14}/></button><button className="pf-top-box" aria-label="账号菜单" onClick={() => action('account')}><UserRound size={20}/><ChevronDown size={14}/></button></div>
    {menu && <section className="pf-top-more" aria-label="更多菜单">{entries.map(([id,label,Icon],index)=><button className={[10,12,13,15].includes(index)?'has-divider':''} key={id} onClick={()=>action(id)}><Icon size={18}/>{label}{id==='search'&&<kbd>Shift+F</kbd>}</button>)}</section>}
  </header>
}
