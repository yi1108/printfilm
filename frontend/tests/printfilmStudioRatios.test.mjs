import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultNodeData } from '../src/features/printfilm-studio/workspacePreferences.ts'
import { writingContext } from '../src/features/printfilm-studio/canvas/writingContext.ts'
import { batchInputs } from '../src/features/printfilm-studio/agent/batchGeneration.ts'

test('image portrait and video landscape defaults agree across creation, writing and batch generation', () => {
  for (const [kind, ratio] of [['image','2:3'],['video','16:9']]) {
    assert.equal(defaultNodeData(kind+'Generation').ratio,ratio)
    for (const saved of [undefined,'','auto','1:1']) {
      const expected=saved==='1:1'?'1:1':ratio
      const media={id:'media',type:kind+'Generation',data:{ratio:saved,prompt:'描述画面'}}
      const writer={id:'writer',type:'text',data:{outputNodeId:'media'}}
      const nodes=[writer,media],settings={imageModel:'image',videoModel:'video'}
      assert.equal(writingContext(writer,nodes,[],settings).outputs[0].ratio,expected)
      assert.equal(batchInputs(['media'],nodes,[],settings)[0].ratio,expected)
    }
  }
})
