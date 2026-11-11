import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { canvasShortcut, isCanvasKeyboardTarget } from '../src/features/printfilm-studio/canvas/canvasShortcuts.ts'
import { captureStudioSelection, pasteStudioSelection, mergeStudioGroups, arrangeStudioNodes, createStudioDragCopy, moveStudioDragCopy } from '../src/features/printfilm-studio/canvas/nodeOperations.ts'

const key = (key, extra = {}) => canvasShortcut({ key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, repeat: false, isComposing: false, ...extra })
test('canvas keyboard commands distinguish modifiers and ignore typing composition and repeats', () => {
  for (const [input, action] of [['Tab','add'],[' ','pan'],['V','select'],['h','hand'],['Delete','remove'],['Escape','escape']]) assert.equal(key(input),action)
  for (const [input, action] of [['g','group'],['a','selectAll'],['c','copy'],['v','paste'],['d','duplicate'],['0','fitView'],['f','search'],['z','undo']]) assert.equal(key(input,{ctrlKey:true}),action)
  assert.equal(key('g',{ctrlKey:true,altKey:true}),'mergeGroup')
  assert.equal(key('g',{altKey:true,shiftKey:true}),'ungroup')
  assert.equal(key('z',{metaKey:true,shiftKey:true}),'redo')
  assert.equal(key('f',{altKey:true,shiftKey:true}),'arrange')
  for (const extra of [{isComposing:true},{repeat:true},{altKey:true},{ctrlKey:true,shiftKey:true}]) assert.equal(key('Delete',extra),undefined)
})

test('canvas shortcuts ignore editors, media, menus, dialogs and Agent controls', () => {
  const dom = new JSDOM('<section class="pf-flow-area"><div id="node"></div><input><video controls></video><div contenteditable="true"><span id="edit">text</span></div></section><div role="dialog"><div id="modal"></div></div><aside class="pf-agent-panel"><span id="agent"></span></aside>')
  const oldElement = globalThis.Element, oldDocument = globalThis.document
  globalThis.Element = dom.window.Element; globalThis.document = dom.window.document
  try {
    assert.equal(isCanvasKeyboardTarget(document.querySelector('#node')),true)
    for (const selector of ['input','video','#edit','#modal','#agent']) assert.equal(isCanvasKeyboardTarget(document.querySelector(selector)),false,selector)
  } finally { globalThis.Element = oldElement; globalThis.document = oldDocument; dom.window.close() }
})

const node = (id, x, y, extra = {}) => ({ id, type:'image', position:{x,y}, data:{ label:id }, ...extra })
test('clipboard captures nested groups and incoming references, then creates independent ids', () => {
  const nodes = [node('ref',0,0),node('group',100,200,{type:'group',data:{children:['child']}}),node('child',20,30,{parentId:'group',extent:'parent'}),node('downstream',600,20)]
  const edges = [{id:'in',source:'ref',target:'child'},{id:'out',source:'child',target:'downstream'}]
  const clip = captureStudioSelection(nodes,edges,new Set(['group']))
  assert.deepEqual(clip.nodes.map(n=>n.id),['group','child'])
  nodes[1].data.children.push('later')
  assert.deepEqual(clip.nodes[0].data.children,['child'])
  const pasted = pasteStudioSelection(nodes,edges,clip)
  const group = pasted.nodes.find(n=>pasted.ids.includes(n.id)&&n.type==='group')
  const child = pasted.nodes.find(n=>pasted.ids.includes(n.id)&&n.type==='image')
  assert.equal(child.parentId,group.id)
  assert.deepEqual(child.position,{x:20,y:30})
  assert.ok(pasted.edges.some(e=>e.source==='ref'&&e.target===child.id))
  assert.equal(pasted.edges.filter(e=>e.target==='downstream').length,1)
})
test('copying a child without its group preserves absolute placement and drops missing external inputs', () => {
  const nodes=[node('outer',100,200,{type:'group'}),node('inner',30,40,{type:'group',parentId:'outer'}),node('child',5,6,{parentId:'inner',extent:'parent'})]
  const clip=captureStudioSelection(nodes,[{id:'external',source:'outer',target:'child'}],new Set(['child']))
  assert.equal(clip.nodes[0].parentId,undefined)
  assert.equal(clip.nodes[0].extent,undefined)
  assert.deepEqual(clip.nodes[0].position,{x:135,y:246})
  const pasted=pasteStudioSelection([],[],clip)
  assert.equal(pasted.edges.length,0)
  assert.deepEqual(pasted.nodes[0].position,{x:183,y:294})
})
test('merging groups preserves child world positions and removes obsolete frame edges', () => {
  const nodes=[node('a',100,100,{type:'group',data:{children:['x']}}),node('x',10,20,{parentId:'a'}),node('b',500,100,{type:'group',data:{children:['y']}}),node('y',30,40,{parentId:'b'})]
  const merged=mergeStudioGroups(nodes,[{id:'ref',source:'x',target:'y'},{id:'frame',source:'a',target:'b'}],new Set(['a','b']))
  assert.ok(merged)
  const group=merged.nodes.find(n=>n.id===merged.id)
  for (const [id,x,y] of [['x',110,120],['y',530,140]]) {
    const child=merged.nodes.find(n=>n.id===id)
    assert.equal(child.parentId,group.id)
    assert.deepEqual({x:child.position.x+group.position.x,y:child.position.y+group.position.y},{x,y})
  }
  assert.deepEqual(merged.edges.map(e=>e.id),['ref'])
})

test('selection arrangement respects large node sizes and keeps nested descendants relative', () => {
  const nodes=[node('group',100,100,{type:'group',style:{width:900,height:600}}),node('child',20,30,{parentId:'group'}),node('wide',200,200,{width:600,height:300}),node('last',400,400)]
  const arranged=arrangeStudioNodes(nodes,new Set(nodes.map(n=>n.id)),'horizontal')
  assert.deepEqual(arranged.find(n=>n.id==='child').position,{x:20,y:30})
  assert.equal(arranged.find(n=>n.id==='wide').position.x,1032)
  assert.equal(arranged.find(n=>n.id==='last').position.x,1664)
})

test('arranging group children expands their frame without changing the group position', () => {
  const nodes=[node('group',100,200,{type:'group',style:{width:400,height:400}}),node('a',20,40,{parentId:'group',width:320,height:200}),node('b',30,50,{parentId:'group',width:320,height:200})]
  const arranged=arrangeStudioNodes(nodes,new Set(['a','b']),'horizontal')
  const frame=arranged.find(n=>n.id==='group'), last=arranged.find(n=>n.id==='b')
  assert.deepEqual(frame.position,{x:100,y:200})
  assert.ok(frame.style.width>=last.position.x+last.width+28)
  assert.ok(frame.style.height>=400)
})

test('drag copy restores originals and moves only copies, with optional incoming reference edges', () => {
  const nodes=[node('ref',0,0),node('group',100,200,{type:'group',data:{children:['child']}}),node('child',20,30,{parentId:'group'}),node('downstream',500,0)]
  const edges=[{id:'in',source:'ref',target:'child'},{id:'out',source:'child',target:'downstream'}]
  for (const withEdges of [false,true]) {
    const drag=createStudioDragCopy(nodes,edges,new Set(['group']),withEdges)
    const moved=moveStudioDragCopy(drag.nodes,drag,[{id:'group',position:{x:400,y:500}},{id:'child',position:{x:20,y:30}}])
    assert.deepEqual(moved.find(n=>n.id==='group').position,{x:100,y:200})
    assert.deepEqual(moved.find(n=>n.id===drag.copies.get('group')).position,{x:400,y:500})
    assert.deepEqual(moved.find(n=>n.id===drag.copies.get('child')).position,{x:20,y:30})
    assert.equal(drag.edges.length,withEdges?3:2)
    assert.equal(drag.edges.filter(e=>e.target==='downstream').length,1)
  }
})
