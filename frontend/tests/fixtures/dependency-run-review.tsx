// Actual workspace with isolated in-memory HTTP. No real project, model or wallet calls.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Workspace from '../../src/features/printfilm-studio/PrintfilmStudioPage'

const writer=(id,label,x,y,extra={})=>({id,type:'text',position:{x,y},style:{width:300,height:190},data:{label,text:'',deferredPrompt:true,writingPrompt:`按下游模型与实际素材生成最终执行提示词。\n创作要求：${label}，汉末三国时期，写实历史电影质感，保持角色与场景一致。`,writingType:'镜头提示词',sourceScriptId:'script',...extra}})
const nodes=[
  {id:'script',type:'script',position:{x:-450,y:0},data:{label:'空城计 · 剧本',text:'魏军斥候向司马懿禀报，城门大开，城楼上诸葛亮抚琴。'}},
  writer('character-write','角色 · 魏军斥候 · 写作',0,0),
  {id:'character',type:'character',position:{x:370,y:0},data:{label:'角色 · 魏军斥候',storyKind:'character',sourceScriptId:'script',promptNodeId:'character-write'}},
  writer('scene-write','场景 · 城门 · 写作',0,380),
  {id:'scene',type:'scene',position:{x:370,y:380},data:{label:'场景 · 城门',storyKind:'scene',sourceScriptId:'script',promptNodeId:'scene-write'}},
  writer('shot-write','分镜01 · 斥候禀报 · 写作',750,0,{referenceNodeIds:['character','scene']}),
  {id:'video',type:'videoGeneration',position:{x:1120,y:0},style:{width:320,height:190},data:{label:'分镜01 · 斥候禀报 · 视频',storyKind:'shot_video',sourceScriptId:'script',promptNodeId:'shot-write',referenceNodeIds:['character','scene'],videoMode:'omni_reference'}}
]
const edges=[['character-write','character'],['scene-write','scene'],['character','shot-write'],['scene','shot-write'],['shot-write','video'],['character','video'],['scene','video']].map(([source,target])=>({id:`${source}-${target}`,source,target}))
let stored={version:1,document:{toonflowCanvas:true,version:1,nodes,edges,viewport:{x:110,y:160,zoom:.65}}}, sessionCount=0
const sessions=new Map(), calls=[]
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="400" height="300" fill="#eee7dc"/><text x="200" y="150" text-anchor="middle" font-size="26" fill="#655c51">参考素材 · 模拟结果</text></svg>'
const media='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg)
const originalFetch=window.fetch.bind(window)
window.fetch=async(input,init)=>{
  const path=new URL(String(input),location.origin).pathname
  let data
  if(String(input).startsWith('data:'))return originalFetch(input,init)
  if(path==='/api/printfilm-studio/projects/999991/info')data={id:999991,title:'依赖运行验收 · 内存样例',is_owner:true}
  else if(path==='/api/drama/projects/999991')data={id:999991,user_id:1,team_id:null,title:'依赖运行验收 · 内存样例',script:''}
  else if(path.endsWith('/workflow'))data={...stored,run:null}
  else if(path.endsWith('/canvas')&&init?.method==='PUT'){stored={document:JSON.parse(init.body).document,version:stored.version+1};data=stored}
  else if(path.endsWith('/canvas'))data=stored
  else if(path.endsWith('/agent/config'))data={models:[{id:'mock-text',label:'测试文字模型'}],tools:[]}
  else if(path.endsWith('/agent/sessions')&&init?.method==='POST'){data={id:`sample-${++sessionCount}`,title:'测试写作',messages:[]};sessions.set(data.id,data)}
  else if(path.endsWith('/agent/sessions'))data={sessions:[]}
  else if(path.match(/\/agent\/sessions\/[^/]+$/)&&init?.method==='PATCH'){data=JSON.parse(init.body);sessions.set(path.split('/').at(-1),data)}
  else if(path.endsWith('/stop'))data={ok:true}
  else if(path.endsWith('/stream')){
    const body=JSON.parse(init.body),id=body.node_ids[0]
    calls.push(`写作完成：${id}`);document.getElementById('review-status').textContent=calls.join(' → ')
    return new Response([{type:'message_delta',content:`已生成提示词：${nodes.find(node=>node.id===id)?.data.label}，写实历史电影质感，汉末三国，固定机位，柔和自然光。`},{type:'done'}].map(event=>JSON.stringify(event)).join('\n')+'\n',{headers:{'Content-Type':'application/x-ndjson'}})
  }
  else if(path.includes('media-models'))data={image_models:[{id:'mock-image',label:'测试图片模型',available:true,allowed_aspect_ratios:['1:1','16:9'],allowed_resolutions:['1K']}],video_models:[{id:'mock-video',label:'测试视频模型',available:true,allowed_aspect_ratios:['16:9','1:1'],allowed_resolutions:['720p']}],defaults:{}}
  else if(path.includes('wallet'))data={balance_yuan:100}
  else if(path.endsWith('/image/estimate')||path.endsWith('/estimate'))data={estimate_yuan:.1,price_version:1}
  else if(path.endsWith('/canvas/assets'))data={assets:[]}
  else if(path.endsWith('/media/source'))return new Response(svg,{headers:{'Content-Type':'image/svg+xml'}})
  else if(path.endsWith('/generations')){const id=init.body.get('node_id');calls.push(`媒体完成：${id}`);document.getElementById('review-status').textContent=calls.join(' → ');data={status:'completed',urls:[media]}}
  else if(path.includes('tasks'))data={items:[],data:[]}
  else return Response.json({detail:`未模拟请求 ${path}`},{status:404})
  return Response.json(data)
}
const root=createRoot(document.getElementById('root'))
root.render(<><MemoryRouter initialEntries={['/drama/projects/999991/printfilm-studio']}><Routes><Route path="/drama/projects/:projectId/printfilm-studio" element={<Workspace/>}/></Routes></MemoryRouter><div id="review-status" style={{position:'fixed',bottom:0,left:0,right:0,zIndex:200,fontSize:11,background:'#f3eef9',color:'#56456e',padding:5}}>内存样例：所有接口均已模拟，不访问真实项目、不生成付费媒体。</div></>)
if(import.meta.hot)import.meta.hot.dispose(()=>{root.unmount();window.fetch=originalFetch})
