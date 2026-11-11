import test from 'node:test'
import assert from 'node:assert/strict'
import { decodeCanvasDocument, encodeCanvasDocument, parseNdjson } from '../src/features/printfilm-studio/canvas/canvasCodec.ts'

test('codec preserves compatibility fields and defaults', () => {
  const doc = decodeCanvasDocument({ toonflowCanvas: true, version: 1, nodes: [], edges: [] })
  assert.equal(doc.viewport.zoom, 1)
  assert.equal(encodeCanvasDocument(doc).toonflowCanvas, true)
})

test('ndjson parser ignores blank lines', () => {
  assert.deepEqual(parseNdjson('{"type":"done"}\n\n'), [{ type: 'done' }])
})

test('flow adapter keeps only persistable node fields', async () => {
  const { documentFromFlow, flowFromDocument } = await import('../src/features/printfilm-studio/canvas/flowAdapter.ts')
  const flow = flowFromDocument({ version: 1, nodes: [{ id: 'n1', type: 'text', position: { x: 3, y: 4 }, data: { label: '开场' } }], edges: [] })
  const saved = documentFromFlow([{ ...flow.nodes[0], selected: true, measured: { width: 10, height: 10 } }], flow.edges, flow.viewport)
  assert.equal(saved.nodes[0].data.label, '开场')
  assert.equal(saved.nodes[0].selected, undefined)
})

test('group geometry and port information survive a flow round trip', async () => {
  const { documentFromFlow, flowFromDocument } = await import('../src/features/printfilm-studio/canvas/flowAdapter.ts')
  const flow = flowFromDocument({ nodes: [{ id: 'g', type: 'group', position: { x: 0, y: 0 }, style: { width: 600, height: 400 } }, { id: 'n', type: 'image', position: { x: 30, y: 50 }, parentId: 'g', extent: 'parent' }], edges: [{ id: 'e', source: 'g', target: 'n', sourceHandle: 'output', targetHandle: 'input' }] })
  const saved = documentFromFlow(flow.nodes, flow.edges, flow.viewport)
  assert.equal(saved.nodes[1].parentId, 'g')
  assert.equal(saved.nodes[0].style.width, 600)
  assert.equal(saved.edges[0].sourceHandle, 'output')
})
