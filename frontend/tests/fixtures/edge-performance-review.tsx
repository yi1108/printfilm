import React, { memo, useCallback, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ReactFlow, Background, Handle, Position, applyEdgeChanges, applyNodeChanges } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { studioEdgeTypes } from '../../src/features/printfilm-studio/canvas/StudioEdge'
import { StudioNodeActionsContext } from '../../src/features/printfilm-studio/canvas/studioNodeContext'
import { visibleStoryEdges } from '../../src/features/printfilm-studio/canvas/storyEdgeVisibility'
import '../../src/features/printfilm-studio/printfilmStudio.css'
import '../../src/features/printfilm-studio/canvas/canvasRefinements.css'

const Tile = memo(({ data }) => <div style={{width:180,height:110,background:'#fff',border:'1px solid #dce2eb',borderRadius:10,padding:14,boxSizing:'border-box',color:'#425166',fontSize:13}}><Handle type="target" position={Position.Left}/>{data.label}<Handle type="source" position={Position.Right}/></div>)
const nodeTypes = { tile: Tile }
const initialNodes = [], initialEdges = []
for (let i=0;i<6;i++) initialNodes.push({id:`asset-${i}`,type:'tile',position:{x:30,y:i*180},data:{storyKind:i<3?'character':'scene',label:`参考素材 ${i+1}`}})
for (let i=0;i<80;i++) {
  const p=`p${i}`,v=`v${i}`,x=400+Math.floor(i/10)*600,y=(i%10)*180
  initialNodes.push({id:p,type:'tile',position:{x,y},data:{storyKind:'shot_prompt',outputNodeId:v,label:`镜头 ${i+1} · 写作`}}, {id:v,type:'tile',position:{x:x+260,y},data:{storyKind:'shot_video',promptNodeId:p,label:`镜头 ${i+1} · 视频`}})
  initialEdges.push({id:`${p}-${v}`,source:p,target:v})
  for(const ref of [`asset-${i%3}`,`asset-${3+i%3}`]) for(const target of [p,v]) initialEdges.push({id:`${ref}-${target}`,source:ref,target})
}
function Review() {
  const [nodes,setNodes]=useState(initialNodes),[edges,setEdges]=useState(initialEdges),[focus,setFocus]=useState(false),[shown,setShown]=useState(true),[selection,setSelection]=useState([]),[tick,setTick]=useState(0)
  const onSelection = useCallback(({nodes}) => setSelection(current => {const next=nodes.map(node=>node.id);return current.join()===next.join()?current:next}),[])
  const displayed=useMemo(()=>shown?visibleStoryEdges(nodes,edges,selection,focus):[],[nodes,edges,selection,focus,shown])
  const actions={writable:true,disconnectEdge(id){setEdges(items=>items.filter(edge=>edge.id!==id))},tick}
  return <StudioNodeActionsContext.Provider value={actions}><div className="pf-studio-shell is-light"><header style={{height:48,display:'flex',gap:14,alignItems:'center',padding:'0 16px',background:'white'}}><button onClick={()=>setFocus(value=>!value)}>聚焦参考线</button><button onClick={()=>setShown(value=>!value)}>切换连线</button><button onClick={()=>setTick(value=>value+1)}>面板状态</button><output>{displayed.length} / {edges.length}</output></header><div className="pf-flow-area" style={{height:'calc(100vh - 48px)'}}><ReactFlow nodes={nodes} edges={displayed} nodeTypes={nodeTypes} edgeTypes={studioEdgeTypes} defaultViewport={{x:25,y:35,zoom:.8}} minZoom={.1} onNodesChange={changes=>setNodes(current=>applyNodeChanges(changes,current))} onEdgesChange={changes=>setEdges(current=>applyEdgeChanges(changes,current))} onSelectionChange={onSelection} panOnDrag={[0,1]}><Background gap={22}/></ReactFlow></div></div></StudioNodeActionsContext.Provider>
}
const root=createRoot(document.getElementById('root'))
root.render(<Review/> )
if(import.meta.hot)import.meta.hot.dispose(()=>root.unmount())
