import test from 'node:test'
import assert from 'node:assert/strict'
import { createEventCursor } from '../src/features/printfilm-studio/agent/eventCursor.ts'

test('reconnect skips duplicate deltas and rejects events from a different run', () => {
  const cursor = createEventCursor()
  assert.equal(cursor.accept({ type: 'session', run_id: 'a', sequence: 1 }), true)
  assert.equal(cursor.accept({ type: 'message_delta', run_id: 'a', sequence: 2 }), true)
  assert.equal(cursor.accept({ type: 'message_delta', run_id: 'a', sequence: 2 }), false)
  assert.equal(cursor.accept({ type: 'message_delta', run_id: 'b', sequence: 3 }), false)
  assert.equal(cursor.sequence, 2)
})
test('missing events cannot silently advance replay cursor', () => {
  const cursor = createEventCursor('a')
  assert.throws(() => cursor.accept({ run_id: 'a', sequence: 2 }))
  assert.equal(cursor.sequence, 0)
  assert.equal(cursor.accept({ type: 'heartbeat' }), false)
  cursor.accept({ type: 'done', run_id: 'a', sequence: 1 })
  assert.equal(cursor.done, true)
})
