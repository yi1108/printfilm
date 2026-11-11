import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ReactFlow, Background, Controls, applyNodeChanges } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { StudioNodeCard } from '../../src/features/printfilm-studio/canvas/StudioNodeCard'
import { StudioNodeActionsContext } from '../../src/features/printfilm-studio/canvas/studioNodeContext'
import { studioEdgeTypes } from '../../src/features/printfilm-studio/canvas/StudioEdge'
import { organizeCanvas } from '../../src/features/printfilm-studio/canvas/organizeCanvas'
import '../../src/features/printfilm-studio/printfilmStudio.css'
import '../../src/features/printfilm-studio/sourceParity.css'
import '../../src/features/printfilm-studio/agent/agentPanel.css'
import '../../src/features/printfilm-studio/canvas/canvasRefinements.css'

const types = Object.fromEntries(['script','text','character','scene','videoGeneration','group'].map(key=>[key,StudioNodeCard]))
const body = Array.from({length:24},(_,i)=>`**第 ${i+1} 段**\n\n桃园春日，刘备、关羽、张飞相对而立。镜头从枝头缓缓落下，三人举杯立誓。风穿过花枝，衣袍轻动。`).join('\n\n')
const writing = {id:'writing',type:'script',position:{x:0,y:0},width:700,height:420,style:{width:700,height:420},selected:true,data:{label:'写作节点 · 拖大后正文填满卡片',text:body}}
const sampleNodes = [], sampleEdges = []
for(const ep of [1,2]) {
  const script = `s${ep}`
  sampleNodes.push({id:script,type:'script',position:{x:20,y:20},width:400,height:280,data:{label:`第${ep}集 · 桃园故事`,episodeNumber:ep,text:body.slice(0,550)}})
  for(const [kind,names] of [['character',['刘备','关羽']],['scene',['桃园','酒肆']],['shot_video',['桃园远景','三人举杯','结义特写']]]) {
    names.forEach((name,index)=>{
      const id=`${ep}-${kind}-${index}`,p=`${id}-text`,common={sourceScriptId:script,episodeNumber:ep,shotIndex:index+1}
      sampleNodes.push({id:p,type:'text',position:{x:0,y:0},width:260,height:180,data:{...common,storyKind:kind==='shot_video'?'shot_prompt':`${kind}_prompt`,label:`${name} · 写作`,text:`${name}，写实历史电影风格，采用柔和自然光。`,outputNodeId:id}})
      sampleNodes.push({id,type:kind==='shot_video'?'videoGeneration':kind,position:{x:0,y:0},width:220,height:kind==='shot_video'?180:260,data:{...common,storyKind:kind,label:name,promptNodeId:p}})
      sampleEdges.push({id:`${p}->${id}`,source:p,target:id})
      if(kind==='shot_video')for(const source of [`${ep}-character-0`,`${ep}-scene-0`])sampleEdges.push({id:`${source}->${id}`,source,target:id})
    })
  }
}

function Review() {
  const [nodes,setNodes]=useState([writing]),[edges,setEdges]=useState([]),[mode,setMode]=useState('writing'),[notice,setNotice]=useState('内存样例 · 可拖动右下角调整正文卡片大小')
  const actions={writable:true,checkpoint(){},resize(id,width,height){setNodes(current=>current.map(node=>node.id===id?{...node,width,height,style:{...node.style,width,height}}:node))},rename(){},contextMenu(){},inspect(){},download(){},remove(){},duplicate(){},ask(){},generateText(){},closeTextComposer(){},updateText(){}}
  const organize=()=>{const result=organizeCanvas(mode==='writing'?sampleNodes:nodes,sampleEdges);setNodes(result.nodes);setEdges(sampleEdges);setMode('organized');setNotice(`已按分集和类别整理 · ${result.sections.map(item=>item.label).join(' / ')}`)}
  return <StudioNodeActionsContext.Provider value={actions}><div className="pf-studio-shell is-immersive is-light">
    <header style={{height:48,display:'flex',alignItems:'center',gap:12,padding:'0 16px',background:'#fff',zIndex:10}}><button onClick={()=>{setNodes([writing]);setEdges([]);setMode('writing');setNotice('内存样例 · 可拖动右下角调整正文卡片大小')}}>写作节点</button><button onClick={organize}>按分集整理画布</button><span style={{fontSize:11,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{notice}</span></header>
    <div className="pf-flow-area"><ReactFlow key={mode} nodes={nodes} edges={edges} nodeTypes={types} edgeTypes={studioEdgeTypes} defaultViewport={{x:60,y:80,zoom:1}} minZoom={.05} fitView={mode==='organized'} fitViewOptions={{padding:.08}} onNodesChange={changes=>setNodes(current=>applyNodeChanges(changes,current))} proOptions={{hideAttribution:true}}><Background gap={22} color="#cbd1de"/><Controls/></ReactFlow></div>
  </div></StudioNodeActionsContext.Provider>
}
const root=createRoot(document.getElementById('root'))
root.render(<Review/> )
if(import.meta.hot)import.meta.hot.dispose(()=>root.unmount())
