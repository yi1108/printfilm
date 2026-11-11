import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import {ReactFlow, Background} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {BatchRunDialog} from '../../src/features/printfilm-studio/agent/BatchRunDialog'
import {batchInputs} from '../../src/features/printfilm-studio/agent/batchGeneration'
import {AgentPanel} from '../../src/features/printfilm-studio/agent/AgentPanel'
import {StudioNodeCard} from '../../src/features/printfilm-studio/canvas/StudioNodeCard'
import {applyProposal} from '../../src/features/printfilm-studio/agent/proposals'
import {decodeCanvasDocument} from '../../src/features/printfilm-studio/canvas/canvasCodec'
import {printfilmStudioApi} from '../../src/features/printfilm-studio/api'
import '../../src/features/printfilm-studio/printfilmStudio.css'
import '../../src/features/printfilm-studio/studioEditors.css'
import '../../src/features/printfilm-studio/sourceParity.css'
import '../../src/features/printfilm-studio/agent/agentPanel.css'
import '../../src/features/printfilm-studio/canvas/canvasRefinements.css'
import fixture from './agent-review.json'
const types=Object.fromEntries(['script','text','character','scene','videoGeneration','group'].map(key=>[key,StudioNodeCard]))
printfilmStudioApi.agentConfig=async()=>({models:[{id:'sample',label:'示例文字模型'}],tools:['read_canvas','plan_story_assets','plan_story_shots']})
printfilmStudioApi.listSessions=async()=>({sessions:[{id:'demo',project_id:1,title:'以这个剧本规划角色、场景和分镜',status:'idle'}]})
function Preview(){
 const [doc,setDoc]=useState(()=>decodeCanvasDocument(fixture.base)),[events,setEvents]=useState([{type:'user',text:'以这个剧本规划角色、场景和分镜'},{type:'proposal',text:'',data:fixture.assetProposal}]),[prompt,setPrompt]=useState(''),[selected,setSelected]=useState([]),[dockWidth,setDockWidth]=useState(400),[batchIds,setBatchIds]=useState([]),[notice,setNotice]=useState('样例验收 · 所有操作仅保存在本页内存中')
 return <div className="pf-studio-shell is-immersive is-light" style={{position:'fixed',inset:0}}><div style={{position:'absolute',top:15,left:20,zIndex:10,font:'13px system-ui',color:'#787482'}}>{notice}</div><div className="pf-flow-area" style={{position:'absolute',inset:`45px ${dockWidth}px 0 0`}}><ReactFlow minZoom={0.05} key={doc.nodes.length} nodes={doc.nodes} edges={doc.edges} nodeTypes={types} fitView fitViewOptions={{padding:.13,maxZoom:.65}} onNodeClick={(_,n)=>setSelected([n.id])} proOptions={{hideAttribution:true}}><Background gap={22} size={1} color="#cfcbd7"/></ReactFlow></div><AgentPanel projectId={1} sessionId="demo" events={events} answer="" running={false} prompt={prompt} nodes={doc.nodes} edges={doc.edges} assets={[]} headers={{}} writable selectedNodeIds={selected} onDockWidth={setDockWidth} onHistoryChange={()=>{}} onPrompt={setPrompt} onSend={async()=>setEvents(current=>[...current,{type:'user',text:'继续计划的下一步：规划分镜视频'},{type:'proposal',text:'',data:fixture.shotProposal}])} onGenerateMedia={()=>setNotice('样例：此处打开真实生成参数面板')} onRepairStory={async()=>{}} onStop={()=>{}} onSelectSession={()=>{}} onClose={()=>{}} proposals={{nodes:doc.nodes,states:doc.agentProposalStates||{},writable:true,busy:false,onAction:async(p,a)=>setDoc(current=>applyProposal(current,p,a)),onRun:setBatchIds}}/>{!!batchIds.length && <BatchRunDialog nodes={doc.nodes.filter(n=>batchIds.includes(n.id))} imageModels={[{id:'sample-image',label:'验收图片模型',allowed_resolutions:['2K'],allowed_aspect_ratios:['3:2']}]} videoModels={[{id:'sample-video',label:'验收视频模型',allowed_resolutions:['720p'],allowed_aspect_ratios:['16:9']}]} balance={100} onQuote={async(settings)=>{const inputs=batchInputs(batchIds,doc.nodes,doc.edges,settings);return {settings,items:inputs.map(input=>({input,yuan:1})),total:inputs.length}}} onRun={async()=>{setNotice('样例：已验证运行回调，没有提交付费任务')}} onClose={()=>setBatchIds([])}/>}</div>
}
const previewRoot=createRoot(document.getElementById('root'))
previewRoot.render(<Preview/>)
if (import.meta.hot) import.meta.hot.dispose(()=>previewRoot.unmount())
