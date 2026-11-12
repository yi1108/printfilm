import test from 'node:test'
import assert from 'node:assert/strict'
import { mediaNodeWidth, showNodePanels, cleanNodeTitle } from '../src/features/printfilm-studio/canvas/nodePresentation.ts'
import { duplicateStudioNodes } from '../src/features/printfilm-studio/canvas/nodeOperations.ts'
import { conversationRows, eventFromWire, sessionEvents } from '../src/features/printfilm-studio/agent/conversation.ts'
import { clampPanel, initialPanel, movePanel } from '../src/features/printfilm-studio/agent/panelGeometry.ts'
import { gridTiles } from '../src/features/printfilm-studio/canvas/gridSplit.ts'
import { generationControls } from '../src/features/printfilm-studio/canvas/generationControls.ts'

test('media dimensions respect source proportions independent of composer state', () => {
  assert.equal(mediaNodeWidth('image', 1000, 1500), 178)
  assert.equal(mediaNodeWidth('video', 1920, 1080), 240 * 16 / 9 + 18)
  assert.equal(mediaNodeWidth('image'), 220)
  assert.equal(mediaNodeWidth('image', 1, 10000), 160)
  assert.equal(mediaNodeWidth('image', 10000, 1), 800)
  assert.equal(cleanNodeTitle('  主角  ', '旧名'), '主角')
  assert.equal(cleanNodeTitle('  ', '旧名'), '旧名')
})
test('dragging and multi-selection hide node panels until explicitly reopened', () => {
  assert.equal(showNodePanels(true, 1, false, false), true)
  for (const params of [[false, 1, false, false], [true, 2, false, false], [true, 1, true, false], [true, 1, false, true]]) assert.equal(showNodePanels(...params), false)
})
test('copying generation node keeps incoming references but never copies outgoing links', () => {
  const nodes = ['ref', 'generate', 'next'].map((id) => ({ id, position: { x: 0, y: 0 }, data: {} }))
  const edges = [{ id: 'in', source: 'ref', target: 'generate' }, { id: 'out', source: 'generate', target: 'next' }]
  const copied = duplicateStudioNodes(nodes, edges, new Set(['generate']))
  assert.equal(copied.edges.length, 3)
  assert.equal(copied.edges[2].source, 'ref')
  assert.equal(copied.edges[2].target, copied.ids[0])
})
test('tool rows pair repeated calls by run and call id without losing inputs', () => {
  const events = [
    { type: 'tool_start', tool: 'read_canvas', run_id: 'a', call_id: '0', data: { version: 1 } },
    { type: 'tool_start', tool: 'read_canvas', run_id: 'a', call_id: '1', data: { version: 2 } },
    { type: 'tool_result', tool: 'read_canvas', run_id: 'a', call_id: '1', ok: false, data: { error: 'conflict' } },
    { type: 'tool_result', tool: 'read_canvas', run_id: 'a', call_id: '0', ok: true, data: { nodes: 2 } },
  ].map(eventFromWire)
  const rows = conversationRows(events, false)
  assert.equal(rows.length, 2)
  assert.deepEqual(rows[0].input, { version: 1 })
  assert.deepEqual(rows[0].data, { nodes: 2 })
  assert.equal(rows[0].state, 'completed')
  assert.equal(rows[1].state, 'failed')
})
test('history restores traces before assistant text and unfinished tools stop spinning', () => {
  const events = sessionEvents({ messages: [
    { id: 'user', role: 'user', content: '读取', sequence: 1 },
    { id: 'answer', role: 'assistant', content: '', sequence: 2, metadata: { events: [{ type: 'tool_start', tool: 'read_canvas' }] } },
  ] })
  assert.deepEqual(events.map((e) => e.type), ['user', 'tool_start', 'assistant'])
  assert.equal(events[2].id, 'answer')
  assert.equal(conversationRows(events, false)[1].state, 'interrupted')
})

test('message references survive session restoration and conversation grouping', () => {
  const references = [{ key: 'node-image-1', nodeId: 'image-1', kind: 'image', label: '主角', thumbnail: '/chosen.png', mediaUrl: '/chosen.png', text: '' }]
  const events = sessionEvents({ messages: [{ id: 'user', role: 'user', content: '请参考主角', sequence: 1, metadata: { references } }] })
  assert.deepEqual(events[0].references, references)
  assert.deepEqual(conversationRows(events, false)[0].references, references)
  assert.equal(events[0].text, '请参考主角')
})
test('panel move and resize remain inside viewport, left resize preserves opposite edge', () => {
  const viewport = { width: 1440, height: 900 }
  const rect = initialPanel(viewport)
  const moved = movePanel(rect, 'move', -4000, -4000, viewport, false)
  assert.equal(moved.left, 15); assert.equal(moved.top, 15)
  const left = movePanel(rect, 'left', -200, 0, viewport, false)
  assert.equal(left.left + left.width, rect.left + rect.width)
  const right = movePanel(rect, 'right', 10000, 0, viewport, false)
  assert.equal(right.left + right.width, viewport.width - 15)
  const bottom = movePanel(rect, 'bottom', 0, 10000, viewport, false)
  assert.equal(bottom.top + bottom.height, viewport.height - 15)
})
test('docked panel reserves right width and fits even a narrow viewport', () => {
  const rect = { left: 1000, top: 300, width: 900, height: 700 }
  const docked = clampPanel(rect, { width: 1000, height: 600 }, true)
  assert.deepEqual(docked, { left: 550, top: 20, width: 450, height: 560 })
  const narrow = clampPanel(rect, { width: 280, height: 200 }, false)
  assert.deepEqual(narrow, { left: 15, top: 15, width: 250, height: 170 })
})

test('grid split covers odd-sized images exactly once without missing border pixels', () => {
  const tiles = gridTiles(101, 73, 3, 4)
  assert.equal(tiles.length, 12)
  const coverage = new Uint8Array(101 * 73)
  for (const tile of tiles) for (let y = tile.y; y < tile.y + tile.height; y++) for (let x = tile.x; x < tile.x + tile.width; x++) coverage[y * 101 + x]++
  assert.ok(coverage.every((count) => count === 1))
  assert.deepEqual(tiles[0], { row: 0, column: 0, x: 0, y: 0, width: 25, height: 24 })
  assert.throws(() => gridTiles(100, 100, 11, 2))
  assert.throws(() => gridTiles(1, 1, 2, 2))
  assert.throws(() => gridTiles(100, 100, 1, 1))
})

test('generation controls honor available model parameters instead of hardcoded resolution and duration', () => {
  const video = generationControls({ available_resolutions: ['720p'], allowed_resolutions: ['480p', '720p'], allowed_aspect_ratios: ['16:9'], duration_min: 2, duration_max: 4 }, true)
  assert.deepEqual(video, { resolutions: ['720p'], ratios: ['16:9'], durations: ['2', '3', '4'] })
  const image = generationControls({ allowed_aspect_ratios: ['1:1'], allowed_resolutions: ['2K'] }, false)
  assert.deepEqual(image.ratios, ['auto', '1:1'])
  assert.deepEqual(image.resolutions, ['2K'])
})
