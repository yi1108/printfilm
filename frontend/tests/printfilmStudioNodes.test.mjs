import test from 'node:test'
import assert from 'node:assert/strict'
import { nodeMediaKind, arrangeStudioNodes, createStudioGroup, groupStudioNodes, duplicateStudioNodes, removeStudioNodes, ungroupStudioNodes, updateStudioNode, validateStudioConnection } from '../src/features/printfilm-studio/canvas/nodeOperations.ts'

const nodes = [
  { id: 'a', type: 'text', position: { x: 10, y: 20 }, data: { label: '甲' } },
  { id: 'b', type: 'image', position: { x: 40, y: 80 }, data: { label: '乙' } },
  { id: 'g', type: 'group', position: { x: 0, y: 0 }, data: { children: ['a', 'b'] } },
]
const edges = [{ id: 'e1', source: 'a', target: 'b' }]

test('connection validation rejects self links and duplicates', () => {
  assert.equal(validateStudioConnection({ source: 'a', target: 'a' }, nodes, edges), '不能连接到节点自身')
  assert.equal(validateStudioConnection({ source: 'a', target: 'b' }, nodes, edges), '这两个节点已经连接')
  assert.equal(validateStudioConnection({ source: 'b', target: 'a' }, nodes, edges), undefined)
})

test('duplicate keeps node data and internal edges', () => {
  const result = duplicateStudioNodes(nodes, edges, new Set(['a', 'b']))
  assert.equal(result.ids.length, 2)
  assert.equal(result.nodes.length, 5)
  assert.equal(result.edges.length, 2)
  assert.equal(result.nodes.find((node) => node.id === result.ids[0]).data.label, '甲')
})

test('duplicated group points to copied members and editing copied data leaves originals intact', () => {
  const original = [{ id: 'a', type: 'image', position: { x: 0, y: 0 }, data: { config: { ratio: '1:1' } } }, { id: 'g', type: 'group', position: { x: 0, y: 0 }, data: { children: ['a'] } }]
  const result = duplicateStudioNodes(original, [], new Set(['a', 'g']))
  const image = result.nodes.find((node) => node.id === result.ids[0])
  const group = result.nodes.find((node) => node.id === result.ids[1])
  assert.deepEqual(group.data.children, [image.id])
  image.data.config.ratio = '16:9'
  assert.equal(original[0].data.config.ratio, '1:1')
})

test('remove drops connected edges and group membership', () => {
  const result = removeStudioNodes(nodes, edges, new Set(['b']))
  assert.deepEqual(result.nodes.map((node) => node.id), ['a', 'g'])
  assert.deepEqual(result.edges, [])
  assert.deepEqual(result.nodes[1].data.children, ['a'])
})

test('arrange and ungroup only move the requested nodes', () => {
  const arranged = arrangeStudioNodes(nodes, new Set(['a', 'b']), 'horizontal')
  assert.equal(arranged[0].position.x, 10)
  assert.ok(arranged[1].position.x > arranged[0].position.x + 280, 'default-width nodes have a visible gap')
  assert.equal(arranged[1].position.y, arranged[0].position.y)
  assert.equal(arranged[2].position.x, 0)
  const ungrouped = ungroupStudioNodes(nodes, new Set(['g']))
  assert.deepEqual(ungrouped.map((node) => node.id), ['a', 'b'])
})

test('node update merges data without dropping existing fields', () => {
  const next = updateStudioNode(nodes, 'a', { text: '开场', prompt: '夜景' })
  assert.equal(next[0].data.label, '甲')
  assert.equal(next[0].data.text, '开场')
})

test('grouping uses parent-relative coordinates and ungroup restores positions', () => {
  const group = createStudioGroup(nodes.slice(0, 2), new Set(['a', 'b']))
  const grouped = groupStudioNodes(nodes.slice(0, 2), group)
  assert.equal(grouped[0].id, group.id)
  assert.equal(grouped[1].parentId, group.id)
  assert.equal(grouped[1].position.x + group.position.x, nodes[0].position.x)
  const moved = grouped.map((node) => node.id === group.id ? { ...node, position: { x: group.position.x + 100, y: group.position.y + 50 } } : node)
  const ungrouped = ungroupStudioNodes(moved, new Set([group.id]))
  assert.equal(ungrouped[0].position.x, nodes[0].position.x + 100)
  assert.equal(ungrouped[0].position.y, nodes[0].position.y + 50)
  assert.equal(ungrouped[0].parentId, undefined)
  const copied = duplicateStudioNodes(grouped, [], new Set([group.id]))
  assert.equal(copied.ids.length, 3)
  const removed = removeStudioNodes(grouped, [], new Set([group.id]))
  assert.equal(removed.nodes.length, 0)
})
test('generation node types retain media kind before their first result', () => {
  assert.equal(nodeMediaKind({ type: 'imageGeneration', data: {} }), 'image')
  assert.equal(nodeMediaKind({ type: 'videoGeneration', data: {} }), 'video')
  assert.equal(nodeMediaKind({ type: 'audioGeneration', data: {} }), 'audio')
})


test('invalid media references are rejected at connection time for both empty and generated nodes', () => {
  const types = ['text', 'image', 'imageGeneration', 'video', 'audio', 'audioGeneration', 'videoGeneration', 'group']
  const graph = types.map(type => ({ id: type, type, position: { x: 0, y: 0 }, data: {} }))
  const check = (source, target) => validateStudioConnection({ source, target }, graph, [])
  for (const target of ['image', 'imageGeneration']) {
    assert.match(check('video', target), /不能连接音视频/)
    assert.match(check('audio', target), /不能连接音视频/)
    assert.equal(check('text', target), undefined)
  }
  for (const source of ['image', 'video', 'audio']) assert.equal(check(source, 'videoGeneration'), undefined)
  assert.equal(check('text', 'audioGeneration'), undefined)
  assert.match(check('video', 'audioGeneration'), /只接受文本/)
  assert.match(check('group', 'image'), /分类框/)
})
