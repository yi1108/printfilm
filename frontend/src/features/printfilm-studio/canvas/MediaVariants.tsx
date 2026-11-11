import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { MediaSnapshot } from './mediaHistory'

export function MediaVariants({items,index,video,writable,onSelect,onCompare,onSplit}:{items:MediaSnapshot[];index:number;video:boolean;writable:boolean;onSelect:(index:number)=>void;onCompare:()=>void;onSplit:()=>void}) {
  if(items.length<2)return null
  return <><div className="pf-variant-controls nodrag nopan" onClick={event=>event.stopPropagation()}><button aria-label="上一个版本" disabled={!writable||index<=0} onClick={()=>onSelect(index-1)}><ChevronLeft size={15}/></button><span>{index+1} / {items.length}</span><button aria-label="下一个版本" disabled={!writable||index>=items.length-1} onClick={()=>onSelect(index+1)}><ChevronRight size={15}/></button><button onClick={onCompare}>对比</button><button disabled={!writable} onClick={onSplit}>拆开</button></div><div className="pf-variant-thumbs nodrag nopan nowheel" onClick={event=>event.stopPropagation()}>{items.map((item,i)=><button type="button" key={item.mediaUrl} aria-label={`采用版本 ${i+1}`} aria-pressed={i===index} disabled={!writable} onClick={()=>onSelect(i)}>{video?<video src={item.mediaUrl} muted preload="metadata"/>:<img src={item.mediaUrl} alt={`版本 ${i+1}`}/>}</button>)}</div></>
}
