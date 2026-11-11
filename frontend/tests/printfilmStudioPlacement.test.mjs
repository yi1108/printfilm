import test from 'node:test'
import assert from 'node:assert/strict'
import { newNodePosition, nodeMenuPosition } from '../src/features/printfilm-studio/canvas/nodePlacement.ts'

const canvas = { left: 16, top: 0, width: 1100, height: 884 }
const size = { width: 360, height: 220 }

test('new toolbar nodes remain visible after panning and zooming', () => {
  for (const zoom of [.05, .18, .5, 1, 2]) {
    const viewport = { x: -5000, y: 3000, zoom }
    const node = newNodePosition(canvas, canvas, viewport, size)
    const left = node.x * zoom + viewport.x + canvas.left
    const top = node.y * zoom + viewport.y + canvas.top
    assert.ok(left >= canvas.left && left + size.width * zoom <= canvas.left + canvas.width)
    assert.ok(top >= canvas.top + 80 && top + size.height * zoom <= canvas.top + canvas.height - 80)
  }
})

test('toolbar insertion avoids the open asset library', () => {
  const visible = { ...canvas, left: 540, width: 576 }
  const viewport = { x: 816, y: -635, zoom: .5 }
  const node = newNodePosition(canvas, visible, viewport, size)
  const left = node.x * viewport.zoom + viewport.x + canvas.left
  assert.ok(left >= visible.left)
  assert.ok(left + size.width * viewport.zoom <= visible.left + visible.width)
})

test('automatic insertion avoids an occupied center while explicit positions stay exact', () => {
  const viewport = { x: 0, y: 0, zoom: 1 }
  const occupied = { left: 386, top: 332, width: 360, height: 220 }
  const node = newNodePosition(canvas, canvas, viewport, size, undefined, [occupied])
  const x = node.x + canvas.left, y = node.y + canvas.top
  assert.ok(x + size.width <= occupied.left || x >= occupied.left + occupied.width || y + size.height <= occupied.top || y >= occupied.top + occupied.height)
  const explicit = newNodePosition(canvas, canvas, viewport, size, { x: 400, y: 400 }, [occupied])
  assert.equal(explicit.x + canvas.left, 400)
  assert.equal(explicit.y + canvas.top, 400)
})

test('right-click insertion uses the original point when the menu is moved upwards', () => {
  const point = { x: 800, y: 600 }
  const menu = nodeMenuPosition(point, { width: 1100, height: 884 })
  assert.ok(menu.top < point.y)
  const viewport = { x: 816, y: -635, zoom: .5 }
  const node = newNodePosition(canvas, canvas, viewport, size, menu.position)
  assert.equal(node.x * viewport.zoom + viewport.x + canvas.left, point.x)
  assert.equal(node.y * viewport.zoom + viewport.y + canvas.top, point.y)
})

test('nodes and menus cannot start offscreen on small windows or edge clicks', () => {
  const small = { left: 0, top: 0, width: 250, height: 300 }
  const point = { x: 249, y: 299 }
  const menu = nodeMenuPosition(point, small)
  assert.ok(menu.left >= 12 && menu.top >= 12)
  const node = newNodePosition(small, small, { x: 0, y: 0, zoom: 1 }, size, point)
  assert.ok(node.x >= 0 && node.x < small.width)
  assert.ok(node.y >= 0 && node.y < small.height)
})
