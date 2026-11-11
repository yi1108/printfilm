import test from 'node:test'
import assert from 'node:assert/strict'
import { conversationDisplayRows, sessionEvents } from '../src/features/printfilm-studio/agent/conversation.ts'

test('cards follow their own turn, preserve multiple cards, and stay below streaming prose', () => {
  const events = [
    {type:'user',text:'第一问'}, {type:'proposal',text:'',data:{id:'one'}},
    {type:'assistant',text:'第一答'}, {type:'user',text:'第二问'},
    {type:'proposal',text:'',data:{id:'two'}}, {type:'tool_result',text:'read_canvas',ok:true},
    {type:'proposal',text:'',data:{id:'three'}},
  ]
  const before=structuredClone(events)
  const rows=conversationDisplayRows(events,true,'长剧本尾部')
  assert.deepEqual(rows.map(row=>row.data?.id || row.text),['第一问','第一答','one','第二问','read_canvas','长剧本尾部','two','three'])
  assert.equal(rows[5].streaming,true)
  assert.deepEqual(events,before)
})

test('reloaded history displays the same proposal after its completed message', () => {
  const events=sessionEvents({messages:[{id:'u',role:'user',content:'写剧本'}, {id:'a',role:'assistant',content:'完整剧本',metadata:{events:[{type:'proposal',data:{id:'p'}}]}}]})
  const rows=conversationDisplayRows(events,false)
  assert.deepEqual(rows.map(row=>row.type),['user','assistant','proposal'])
  assert.equal(rows[1].id,'a')
  assert.equal(rows[2].data.id,'p')
})

test('model progress remains status information rather than repeated chat bubbles', () => {
  const rows=conversationDisplayRows([{type:'user',text:'规划'}, {type:'model_progress',text:'等待模型'}, {type:'model_progress',text:'正在接收方案'}],true)
  assert.deepEqual(rows.map(row=>row.type),['user'])
})
