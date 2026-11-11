import test from 'node:test'
import assert from 'node:assert/strict'
import { organizeCanvas, nodeWorldPositions, organizationNodeSize } from '../src/features/printfilm-studio/canvas/organizeCanvas.ts'

const node = (id, type = 'image', extra = {}) => ({ id, type, position: { x: 20, y: 30 }, data: { label: id, custom: { keep: true } }, ...extra })
const noOverlap = (nodes) => {
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    const a = nodes[i], b = nodes[j], as = organizationNodeSize(a), bs = organizationNodeSize(b)
    assert.ok(a.position.x + as.width <= b.position.x || b.position.x + bs.width <= a.position.x || a.position.y + as.height <= b.position.y || b.position.y + bs.height <= a.position.y, `${a.id} overlaps ${b.id}`)
  }
}

test('organizing groups workflows and loose types without losing content or references', () => {
  const nodes = [node('script', 'text'), node('generate', 'imageGeneration', { width: 700, height: 510 }), node('video', 'video'), node('text-2', 'text'), node('audio', 'audio'), node('image-loose')]
  const edges = [{ id: 'a', source: 'script', target: 'generate', sourceHandle: 'text', targetHandle: 'prompt' }, { id: 'b', source: 'generate', target: 'video' }]
  const original = structuredClone({ nodes, edges }), result = organizeCanvas(nodes, edges)
  assert.deepEqual({ nodes, edges }, original, 'layout does not mutate the input or port metadata')
  assert.equal(result.order.length, nodes.length)
  assert.equal(new Set(result.order).size, nodes.length)
  const byId = new Map(result.nodes.map(n => [n.id, n]))
  for (const item of nodes) assert.deepEqual(byId.get(item.id).data, item.data)
  assert.equal(byId.get('script').parentId, byId.get('video').parentId)
  assert.notEqual(byId.get('text-2').parentId, byId.get('script').parentId)
  assert.ok(byId.get('generate').position.x > byId.get('script').position.x)
  assert.ok(byId.get('video').position.x > byId.get('generate').position.x + 700)
  noOverlap(result.nodes.filter(n => !n.parentId))
})

test('large measured nodes, nested user groups and children stay inside non-overlapping frames', () => {
  const nodes = [node('user-group', 'group', { width: 500, height: 400, data: { label: '保留我的分组', custom: 42 } }), node('child', 'image', { parentId: 'user-group', extent: 'parent', measured: { width: 900, height: 600 } }), node('nested', 'group', { parentId: 'user-group' }), node('deep', 'audio', { parentId: 'nested', measured: { width: 410, height: 160 } }), ...Array.from({ length: 13 }, (_, i) => node(`loose-${i}`, 'image', { measured: { width: 220 + i * 25, height: 140 + i * 13 } }))]
  const result = organizeCanvas(nodes, [])
  const byId = new Map(result.nodes.map(n => [n.id, n]))
  assert.equal(byId.get('child').parentId, 'user-group')
  assert.equal(byId.get('deep').parentId, 'nested')
  assert.deepEqual(byId.get('user-group').data, nodes[0].data)
  assert.equal(result.order.length, 15)
  for (const parent of result.nodes.filter(n => n.type === 'group')) {
    const children = result.nodes.filter(n => n.parentId === parent.id)
    noOverlap(children)
    for (const child of children) {
      const size = organizationNodeSize(child)
      assert.ok(child.position.x >= 24 && child.position.y >= 60)
      assert.ok(child.position.x + size.width <= parent.width)
      assert.ok(child.position.y + size.height <= parent.height)
      assert.ok(result.nodes.indexOf(parent) < result.nodes.indexOf(child), 'parents precede descendants')
    }
  }
  noOverlap(result.nodes.filter(n => !n.parentId))
})

test('repeated organization is stable and handles cyclic links', () => {
  const nodes = [node('a'), node('b'), node('c'), node('d', 'text')]
  const edges = [{ id: 'a-b', source: 'a', target: 'b' }, { id: 'b-a', source: 'b', target: 'a' }, { id: 'b-c', source: 'b', target: 'c' }]
  const first = organizeCanvas(nodes, edges), second = organizeCanvas(first.nodes, edges)
  assert.deepEqual(second, first, 'no nested automatic frames accumulate on repeated clicks')
  assert.ok(first.nodes.every(n => Number.isFinite(n.position.x) && Number.isFinite(n.position.y)))
  const world = nodeWorldPositions(first.nodes)
  assert.equal(world.size, first.nodes.length)
  assert.ok(world.get('a').x >= first.nodes.find(n => n.id === first.nodes.find(n => n.id === 'a').parentId).position.x)
})

test('user-group children keep a canonical order even when the original file was unsorted', () => {
  const nodes = [node('group', 'group'), node('z', 'video', { parentId: 'group', width: 500, height: 320 }), node('a', 'image', { parentId: 'group', width: 250, height: 200 })]
  const first = organizeCanvas(nodes, []), second = organizeCanvas(first.nodes, [])
  assert.deepEqual(second, first)
})

test('story images prompts videos and outlines stay in separate sections despite reference edges', () => {
  const nodes = [
    node('s', 'script'),
    node('image', 'character', {data: {sourceScriptId: 's', storyKind: 'character', mediaUrl: '/keep.png'}}),
    node('scene', 'scene', {data: {sourceScriptId: 's', storyKind: 'scene'}}),
    node('outline', 'text', {data: {sourceScriptId: 's', storyKind: 'shot_outline', text: '保留原分镜'}}),
    ...[2, 1].flatMap(index => [node(`p${index}`, 'text', {data: {sourceScriptId: 's', storyKind: 'shot_prompt', shotIndex: index}}), node(`v${index}`, 'videoGeneration', {data: {sourceScriptId: 's', storyKind: 'shot_video', shotIndex: index}})]),
  ]
  const edges = [1, 2].flatMap(index => ['image', 'scene', `p${index}`].map(source => ({id: `${source}-v${index}`, source, target: `v${index}`})))
  const first = organizeCanvas(nodes, edges)
  const byId = new Map(first.nodes.map(n => [n.id, n]))
  assert.deepEqual(first.sections.map(s => s.label), ['剧本 · s', '人物 · s', '场景 · s', '分镜 · s'])
  assert.notEqual(byId.get('image').parentId, byId.get('scene').parentId)
  assert.equal(new Set(['s','image','scene','p1','v1'].map(id => byId.get(id).parentId)).size, 4)
  assert.deepEqual(first.order.filter(id => /^p\d/.test(id)), ['p1', 'p2'])
  assert.equal(byId.get('p1').position.y, byId.get('v1').position.y)
  assert.ok(byId.get('p2').position.y > byId.get('p1').position.y)
  assert.ok(byId.get('v1').position.x > byId.get('p1').position.x)
  assert.deepEqual(organizeCanvas(first.nodes, edges), first)
  noOverlap(first.nodes.filter(n => !n.parentId))
})

test('story groups stay side by side, pair rows stay together, and episodes occupy separate bands', () => {
  const nodes = [node('s', 'script', {width:1200,height:760,data:{label:'主剧本'}})]
  const edges = []
  for (const episode of [2,1]) {
    const group = `characters-${episode}`
    nodes.push(node(group,'group',{data:{sourceScriptId:'s',storyKind:'character_group',episodeNumber:episode}}))
    for (const index of [2,1]) {
      const p=`p-${episode}-${index}`, c=`c-${episode}-${index}`
      nodes.push(node(p,'text',{parentId:group,width:420,height:520,data:{sourceScriptId:'s',storyKind:'character_prompt',outputNodeId:c}}),node(c,'character',{parentId:group,width:380,height:280,data:{sourceScriptId:'s',storyKind:'character',promptNodeId:p}}))
      edges.push({id:p+c,source:p,target:c})
    }
    nodes.push(node(`scene-${episode}`,'scene',{data:{sourceScriptId:'s',storyKind:'scene',episodeNumber:episode}}))
    edges.push({id:`cross-${episode}`,source:`scene-${episode}`,target:`c-${episode}-1`})
  }
  const result=organizeCanvas(nodes,edges), byId=new Map(result.nodes.map(n=>[n.id,n]))
  const first=byId.get('characters-1'), second=byId.get('characters-2')
  assert.ok(second.position.y > first.position.y + first.height)
  const scene=byId.get(byId.get('scene-1').parentId)
  assert.equal(scene.position.y, first.position.y)
  assert.ok(scene.position.x > first.position.x + first.width)
  for(const episode of [1,2])for(const index of [1,2]) {
    const p=byId.get(`p-${episode}-${index}`), c=byId.get(`c-${episode}-${index}`)
    assert.equal(p.position.y,c.position.y)
    assert.ok(c.position.x >= p.position.x + 420)
    assert.equal(c.parentId,`characters-${episode}`)
  }
  noOverlap(result.nodes.filter(n=>!n.parentId))
  for(const g of result.nodes.filter(n=>n.type==='group'))noOverlap(result.nodes.filter(n=>n.parentId===g.id))
  assert.deepEqual(organizeCanvas(result.nodes,edges),result)
})

test('long shot lists continue in adjacent vertical lanes and retain episode IDs',()=>{
  const nodes=[node('s','script')],edges=[]
  for(let index=1;index<=18;index++){
    nodes.push(node(`p${index}`,'text',{height:270,data:{sourceScriptId:'s',storyKind:'shot_prompt',shotIndex:index,episodeId:90}}),node(`v${index}`,'videoGeneration',{height:250,data:{sourceScriptId:'s',storyKind:'shot_video',shotIndex:index,promptNodeId:`p${index}`,episodeId:90}}))
    edges.push({id:`p${index}-v${index}`,source:`p${index}`,target:`v${index}`})
  }
  const first=organizeCanvas(nodes,edges),byId=new Map(first.nodes.map(n=>[n.id,n]))
  assert.equal(byId.get('p9').position.y,byId.get('p1').position.y)
  assert.ok(byId.get('p9').position.x > byId.get('v1').position.x)
  assert.ok(byId.get(byId.get('p1').parentId).height < 3000)
  assert.deepEqual(organizeCanvas(first.nodes,edges),first)
})

test('ordinary media with episode metadata is separated by episode and type',()=>{
  const nodes=[node('a','image',{data:{episodeNumber:1}}),node('b','audio',{data:{episodeNumber:1}}),node('c','image',{data:{episodeNumber:2}})]
  const first=organizeCanvas(nodes,[])
  assert.equal(new Set(first.nodes.filter(n=>n.type!=='group').map(n=>n.parentId)).size,3)
  assert.deepEqual(organizeCanvas(first.nodes,[]),first)
})
