import test from 'node:test'
import assert from 'node:assert/strict'
import { getDramaGenQueue, upsertDramaGenJob } from '../src/lib/dramaGenQueue.ts'
import { setWorkspaceTeam } from '../src/features/teams/workspaceScope.ts'

function addJob(id, title) {
  upsertDramaGenJob({ id, kind: 'image', projectId: 1, targetId: 1, title, subtype: '角色', status: 'running' })
}

test('retired team navigation does not discard the personal task queue', () => {
  setWorkspaceTeam(null,true)
  addJob('personal','个人任务')
  for(const team of [2,3,null]) {
    setWorkspaceTeam(team)
    assert.equal(getDramaGenQueue()[0].title,'个人任务')
  }
})

test('同一空间换账号时清除旧身份队列', () => {
  setWorkspaceTeam(2)
  addJob('old-account', '旧账号任务')
  setWorkspaceTeam(2, true)
  assert.deepEqual(getDramaGenQueue(), [])
  setWorkspaceTeam(null)
})
