import { Check, Sparkles } from 'lucide-react'
import { ComposerMenu } from './canvas/ComposerMenu'
import './studioModelSelect.css'

type ModelOption = { id: string; label: string; disabled?: boolean; hint?: string }
const descriptions: Record<string, string> = {
  'gpt-6.1-sol': '剧本创作 · 分镜提示词 · 日常改写',
  'gpt-6-astra': '复杂叙事 · 细节推敲 · 多重创作要求',
  'deepseek-v4-pro': '中文写作 · 情节梳理 · 扩写润色',
  'seedream-5.0': '角色与场景 · 多图参考 · 静帧创作',
  'gpt-image-2.5': '文字排版 · 多图参考 · 局部精修',
  'seedance-2.0': '镜头创作 · 动作与运镜',
  'seedance-2.5': '镜头创作 · 多模态参考',
  'seedance-2.0-fast': '快速创作 · 分镜预演',
  'minimax-h3': '人物表演 · 动态视频',
}

/** Small vector family marks stay crisp at both menu and toolbar sizes. */
export function StudioModelIcon({ model }: { model: string }) {
  const family = model.toLowerCase()
  return <span className={`pf-model-mark ${family.startsWith('seed') ? 'is-seed' : family.startsWith('deepseek') ? 'is-deepseek' : ''}`} aria-hidden="true">
    {family.startsWith('gpt') ? <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">{Array.from({length:6},(_,i)=><path key={i} transform={`rotate(${i*60} 16 16)`} d="M16 5c-5-3-11 2-8 7l8 5 5-3V8z"/>)}</svg>
      : family.startsWith('seedance') ? <svg viewBox="0 0 32 32" fill="currentColor"><path d="M4 7h4v18H4zM11 13h4v10h-4z" fill="#4468d7"/><path d="M18 10h4v16h-4zM25 4h3v22h-3z" fill="#51d7c8"/></svg>
      : family.startsWith('seedream') ? <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2"><rect x="5" y="5" width="22" height="22" rx="7"/><path d="m6 23 8-10 6 7 4-4 3 4"/><circle cx="22" cy="10" r="2" fill="currentColor" stroke="none"/></svg>
      : family.startsWith('deepseek') ? <svg viewBox="0 0 32 32" fill="currentColor"><path d="M4 14c3-5 11-5 16-1l7-6-1 9 4 1-5 4c-2 5-10 7-16 2-3-2-5-5-5-9Z"/><circle cx="11" cy="15" r="1.3" fill="white"/></svg>
      : <Sparkles size={24}/>}
  </span>
}

export function StudioModelSelect({label,value,options,onChange,large=false,disabled=false}:{label:string;value:string;options:ModelOption[];onChange:(value:string)=>void;large?:boolean;disabled?:boolean}) {
  const selected = options.find(item=>item.id===value)
  return <ComposerMenu label={label} disabled={disabled || !options.length} wide matchWidth={large} className={`pf-model-select${large?' is-large':''}`} menuClassName="pf-model-options" value={<><StudioModelIcon model={value}/><span>{selected?.label || value || '加载模型…'}</span></>}>
    {close=><div role="group" aria-label={label}>{options.map(item=><button type="button" key={item.id} role="menuitemradio" aria-checked={item.id===value} disabled={item.disabled} onClick={()=>{onChange(item.id);close()}}><StudioModelIcon model={item.id}/><span className="pf-model-option-copy"><b>{item.label}</b>{(item.hint || descriptions[item.id.toLowerCase()])&&<small>{item.hint || descriptions[item.id.toLowerCase()]}</small>}</span>{item.id===value&&<Check size={18}/>}</button>)}</div>}
  </ComposerMenu>
}
