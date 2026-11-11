import test from 'node:test'
import assert from 'node:assert/strict'
import { captureRecipe, instantiateRecipe } from '../src/features/printfilm-studio/canvas/recipeGraph.ts'
const document = { nodes: [{ id: 'a', parentId: 'g', position: { x: 10, y: 20 }, data: { prompt: 'Portrait' } }, { id: 'g', type: 'group', position: { x: 100, y: 50 }, data: { children: ['a'] } }, { id: 'b', position: { x: 500, y: 50 }, data: {} }], edges: [{ id: 'e', source: 'a', target: 'b' }] }
test('capture group includes children and drops outside connections', () => {
  const result = captureRecipe(document, ['g'])
  assert.equal(result.nodes.length, 2)
  assert.equal(result.edges.length, 0)
  assert.equal(result.nodes.find((n) => n.id === 'a').position.x, 10)
})
test('reusable recipe instances have unique IDs, parents precede children', () => {
  const template = captureRecipe(document, [])
  const first = instantiateRecipe(template, { x: 900, y: 200 })
  const second = instantiateRecipe(template, { x: 0, y: 0 })
  assert.equal(first.nodes[0].type, 'group')
  assert.ok(first.nodes.every((n) => !second.nodes.some((m) => m.id === n.id)))
  assert.equal(first.nodes.find((n) => n.parentId)?.parentId, first.nodes[0].id)
  assert.ok(first.nodes.some((n) => n.id === first.edges[0].source))
  assert.equal(document.nodes[0].id, 'a')
})
test('capturing a child without its group removes the external parent', () => {
  const captured = captureRecipe(document, ['a'])
  assert.equal(captured.nodes[0].parentId, undefined)
  assert.deepEqual(captured.nodes[0].position, { x: 0, y: 0 })
})
