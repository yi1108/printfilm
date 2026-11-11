import test from 'node:test'
import assert from 'node:assert/strict'
import { displaySegmentCues, canonicalSegmentCues } from '../src/lib/segmentCueDisplay.ts'
import { narrationFromScript, sumDuration } from '../src/lib/segmentDuration.ts'

test('English cue display round-trips without changing narration or duration', () => {
  const raw = '【字幕：Post-production captions】\n【BGM：Warm acoustic folk】\n@duration:3\nFrost on a window.\n@duration:5\n【旁白·自然语速·同步字幕】Ever woken up to find your entire world turned sparkly white?'
  const shown = displaySegmentCues(raw, 'en')
  assert.ok(shown.includes('【Narration · Natural pace · Synced subtitles】'))
  assert.ok(!/[\u3400-\u9fff]/u.test(shown))
  assert.equal(canonicalSegmentCues(shown), raw)
  assert.equal(displaySegmentCues(raw, 'zh'), raw)
  const saved = canonicalSegmentCues(shown.replace('sparkly white?', 'bright white?'))
  assert.match(narrationFromScript(saved), /bright white\?$/)
  assert.equal(sumDuration(saved), 8)
})

test('Only protocol markers change, not user prose', () => {
  assert.equal(displaySegmentCues('旁白是中文正文，Narration is English prose.', 'en'), '旁白是中文正文，Narration is English prose.')
})
