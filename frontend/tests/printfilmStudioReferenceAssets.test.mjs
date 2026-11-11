import test from 'node:test'
import assert from 'node:assert/strict'
import { referenceAssetNode } from '../src/features/printfilm-studio/canvas/referenceAssetNode.ts'

test('library references reuse the existing node by asset id or exact media URL', () => {
  const nodes = [
    { id: 'target', data: { assetId: 10, mediaUrl: '/target.png' } },
    { id: 'character', data: { assetId: 20, mediaUrl: '/character.png' } },
    { id: 'copy', data: { assetId: 21, mediaUrl: '/character.png' } },
  ]
  assert.equal(referenceAssetNode(nodes, { id: 20 }, 'target', []).id, 'character')
  assert.equal(referenceAssetNode(nodes, { id: 30, url: '/character.png' }, 'target', []).id, 'character')
  assert.equal(referenceAssetNode(nodes, { id: 30, url: '/character.png' }, 'target', [{ source: 'copy', target: 'target' }]).id, 'copy')
  assert.equal(referenceAssetNode(nodes, { id: 10, url: '/target.png' }, 'target', []), undefined)
  assert.equal(referenceAssetNode(nodes, { id: 40, url: '/different.png' }, 'target', []), undefined)
  assert.equal(nodes.length, 3)
})
