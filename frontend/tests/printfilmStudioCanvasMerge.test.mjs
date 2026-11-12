import test from 'node:test'
import assert from 'node:assert/strict'
import { CanvasMergeConflict, canvasValuesEqual, mergeCanvasDocuments } from '../src/features/printfilm-studio/canvas/canvasMerge.ts'

const node = (id, data = {}) => ({ id, type: 'text', position: { x: 0, y: 0 }, data })
const canvas = () => ({ toonflowCanvas: true, version: 1, nodes: [node('a', { text: 'before', status: 'running' }), node('b')], edges: [], viewport: { x: 0, y: 0, zoom: 1 } })

test('merges local writing/movement with completed generation and Agent additions', () => {
  const base = canvas(), local = structuredClone(base), remote = structuredClone(base)
  local.nodes[0].data.text = 'typing'; local.nodes[0].position.x = 80; local.nodes[0].selected = true
  local.viewport.zoom = 2
  remote.nodes[0].data.status = 'completed'; remote.nodes[0].data.mediaUrl = '/result.png'
  remote.nodes.push(node('agent')); remote.edges.push({ id: 'link', source: 'a', target: 'agent' })
  const merged = mergeCanvasDocuments(base, local, remote)
  assert.deepEqual(merged.nodes[0].data, { text: 'typing', status: 'completed', mediaUrl: '/result.png' })
  assert.equal(merged.nodes[0].position.x, 80)
  assert.equal(merged.nodes[0].selected, undefined)
  assert.equal(merged.nodes.length, 3); assert.deepEqual(merged.edges, remote.edges)
  assert.equal(merged.viewport.zoom, 2)
  assert.equal(base.nodes[0].data.text, 'before')
})

test('retains edits during an in-flight successful save', () => {
  const sent = canvas(), current = structuredClone(sent), response = structuredClone(sent)
  current.nodes[0].data.text = 'typed while saving'
  response.nodes[0].data.serverField = true
  const merged = mergeCanvasDocuments(sent, current, response)
  assert.equal(merged.nodes[0].data.text, 'typed while saving')
  assert.equal(merged.nodes[0].data.serverField, true)
  assert.equal(canvasValuesEqual(merged, response), false)
})

test('same-field concurrent changes and delete/edit collisions preserve a real conflict', () => {
  const base = canvas(), local = structuredClone(base), remote = structuredClone(base)
  local.nodes[0].data.text = 'local'; remote.nodes[0].data.text = 'remote'
  assert.throws(() => mergeCanvasDocuments(base, local, remote), CanvasMergeConflict)
  remote.nodes.shift()
  assert.throws(() => mergeCanvasDocuments(base, local, remote), CanvasMergeConflict)
})

test('independent deletions merge, but newly added references cannot target deleted nodes', () => {
  const base = canvas(), local = structuredClone(base), remote = structuredClone(base)
  local.nodes.pop(); remote.nodes[0].data.status = 'completed'
  assert.equal(mergeCanvasDocuments(base, local, remote).nodes.length, 1)
  remote.edges.push({ id: 'link', source: 'a', target: 'b' })
  assert.throws(() => mergeCanvasDocuments(base, local, remote), CanvasMergeConflict)
})

test('normalization ignores transient selection and property order', () => {
  const base = canvas(), local = structuredClone(base), remote = structuredClone(base)
  local.nodes[0].measured = { width: 30, height: 60 }; local.nodes[0].selected = true
  remote.nodes[0].data = { status: 'running', text: 'before' }
  assert.equal(canvasValuesEqual(mergeCanvasDocuments(base, local, remote), base), true)
})

test('two pollers observing the same task retain the furthest progress and local writing', () => {
  const base = canvas(), local = structuredClone(base), remote = structuredClone(base)
  for (const doc of [base, local, remote]) doc.nodes[0].data.taskId = 'task-1'
  base.nodes[0].data.status = 'queued'
  Object.assign(local.nodes[0].data, { text: 'my edit', status: 'running', canCancel: true })
  Object.assign(remote.nodes[0].data, { status: 'completed', canCancel: false, mediaUrl: '/result.png' })
  for (const [a, b] of [[local, remote], [remote, local]]) {
    const data = mergeCanvasDocuments(base, a, b).nodes[0].data
    assert.equal(data.status, 'completed'); assert.equal(data.canCancel, false)
    assert.equal(data.text, 'my edit'); assert.equal(data.mediaUrl, '/result.png')
  }
  remote.nodes[0].data.taskId = 'task-2'
  assert.throws(() => mergeCanvasDocuments(base, local, remote), CanvasMergeConflict)
})
