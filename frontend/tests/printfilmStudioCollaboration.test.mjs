import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { setTimeout as delay } from 'node:timers/promises'

test('presence authenticates without URL credentials, relays state, reconnects and cleans up',async()=>{
  const server=await createServer({configFile:false,root:fileURLToPath(new URL('..',import.meta.url)),server:{middlewareMode:true,hmr:false,ws:false,watch:null},logLevel:'error'})
  const instances=[]
  class Socket {
    readyState=0;sent=[]
    constructor(url){this.url=url;instances.push(this)}
    send(value){this.sent.push(JSON.parse(value))}
    close(){this.readyState=3;this.onclose?.({code:1000})}
    open(){this.readyState=1;this.onopen?.()}
    message(value){this.onmessage?.({data:JSON.stringify(value)})}
    disconnect(code){this.readyState=3;this.onclose?.({code})}
  }
  let connection
  try {
    const {connectPresence,absoluteNodePosition}=await server.ssrLoadModule('/src/features/printfilm-studio/collaboration.ts')
    const seen=[],statuses=[]
    connection=connectPresence('ws://localhost/api/printfilm-studio/projects/1/presence','test-token',p=>seen.push(p),s=>statuses.push(s),Socket)
    const socket=instances[0];socket.open()
    assert.equal(socket.url.includes('token'),false)
    assert.deepEqual(socket.sent[0],{token:'test-token'})
    const peers=[{session_id:'self',user_id:1,seen_at:Date.now()/1000},{session_id:'another-tab',user_id:1,seen_at:Date.now()/1000},{session_id:'expired',seen_at:0}]
    socket.message({type:'presence',self_id:'self',peers})
    assert.deepEqual(seen.at(-1).map(p=>p.session_id),['another-tab'])
    connection.update({cursor:{x:123,y:456},action:'dragging',node_ids:['n'],positions:[{id:'n',x:10,y:20}]})
    await delay(130)
    assert.equal(socket.sent.at(-1).action,'dragging')
    assert.deepEqual(socket.sent.at(-1).cursor,{x:123,y:456})
    const now=Date.now, beforeHeartbeat=socket.sent.length, later=now()+6000
    try {Date.now=()=>later;socket.message({type:'presence',self_id:'self',peers})} finally {Date.now=now}
    assert.equal(socket.sent.length,beforeHeartbeat+1,'server snapshots keep background tabs alive when interval timers are throttled')
    socket.disconnect(1006);assert.equal(statuses.at(-1),'offline');assert.deepEqual(seen.at(-1),[])
    await delay(550)
    assert.equal(instances.length,2)
    instances[1].open();instances[1].message({type:'presence',self_id:'new',peers:[]})
    assert.equal(instances[1].sent.at(-1).action,'dragging')
    instances[1].disconnect(4403);assert.equal(statuses.at(-1),'denied')
    await delay(550);assert.equal(instances.length,2)
    const group={id:'g',position:{x:100,y:200}},node={id:'n',parentId:'g',position:{x:20,y:30}}
    assert.deepEqual(absoluteNodePosition(node,[group,node]),{x:120,y:230})
    connection.close();assert.equal(instances[1].onmessage,null)
  } finally {connection?.close();await server.close()}
})
