import test from 'node:test'
import assert from 'node:assert/strict'
import { imageWritingRequirements, textWritingPrompt } from '../src/features/printfilm-studio/canvas/textWriting.ts'

test('image writing removes legacy planning commands and preserves visual blank-space constraints', () => {
  const facts = '现代小饭馆后厨，灶台与取餐窗相邻。招牌留空，无字幕。'
  for (const prefix of ['仅填写生成参考图提示词的写作要求，正文留空。', '只写参考图提示词的创作要求写作要求，正文留空。', '只填写参考图提示词写作要求，正文留空。', '写作节点正文留空，运行时再按素材和下游模型生成最终提示词。', '仅记录提示词写作要求，正文留空，最终提示词运行时生成。', '只写参考图提示词的创作要求写作要求，写作正文留空。']) {
    assert.equal(imageWritingRequirements(prefix + facts), facts)
    const wrapped = '根据下游图片模型、已连接的参考素材和以下创作要求，生成最终可执行的中文图片提示词。规则。\n\n创作要求：\n' + prefix + facts
    assert.equal(imageWritingRequirements(wrapped), facts)
    const request = textWritingPrompt('图片提示词', '', wrapped, '## 参考图提示词写作要求', [])
    assert.ok(request.includes('创作要求：' + facts))
    assert.ok(!request.includes('创作要求：' + prefix))
    assert.ok(request.includes('不能再次要求另一个写作者生成提示词'))
    assert.ok(!request.includes('可使用 Markdown'))
  }
  assert.equal(imageWritingRequirements(facts), facts)
  assert.ok(textWritingPrompt('故事脚本', '', '正文留空。', '', []).includes('创作要求：正文留空。'))
})
