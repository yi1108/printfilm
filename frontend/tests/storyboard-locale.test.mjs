import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { storyboardEnglish, storyboardText, storyboardError, storyboardTemplateName } from '../src/i18n/storyboardText.ts'
import { applyLocale } from '../src/i18n/detect.ts'

const source = readFileSync(new URL('../src/pages/studio/StoryboardPage.tsx', import.meta.url), 'utf8')
const page = ts.createSourceFile('StoryboardPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const han = /\p{Script=Han}/u

/** Visit TSX without treating comments or user-generated script data as static UI. */
function descendants(predicate) {
  const found = []
  function visit(node) {
    if (predicate(node)) found.push(node)
    ts.forEachChild(node, visit)
  }
  visit(page)
  return found
}

test('storyboard static bilingual dictionary covers every page translation key', () => {
  const calls = descendants(node => ts.isCallExpression(node) && ['st', 'storyboardText'].includes(node.expression.getText(page)))
  assert.ok(calls.length > 130)
  for (const call of calls) {
    const key = call.arguments[0]
    if (!ts.isStringLiteral(key)) continue
    assert.ok(storyboardEnglish[key.text], `Missing own storyboard key: ${key.text}`)
  }
  for (const [zh, en] of Object.entries(storyboardEnglish)) {
    assert.ok(en.trim())
    assert.doesNotMatch(en, han, zh)
    const tokens = value => [...value.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort()
    assert.deepEqual(tokens(en), tokens(zh), `Interpolation parity: ${zh}`)
    assert.equal(storyboardText(zh, {}, 'zh'), zh)
    assert.equal(storyboardText(zh, {}, 'en'), en)
  }
})

test('all visible JSX literals and templates are localized, not DOM-translated', () => {
  for (const node of descendants(node => ts.isJsxText(node) || ts.isTemplateExpression(node))) {
    const literal = ts.isTemplateExpression(node) ? node.head.text + node.templateSpans.map(span => span.literal.text).join('') : node.text
    assert.doesNotMatch(literal, han, `Raw UI: ${node.getText(page)}`)
  }
  const attributes = descendants(node => ts.isJsxAttribute(node) && ['title', 'placeholder', 'aria-label'].includes(node.name.getText(page)))
  for (const node of attributes) {
    if (node.initializer && ts.isStringLiteral(node.initializer)) assert.doesNotMatch(node.initializer.text, han)
  }
  assert.match(source, /const \{ locale \} = useI18n\(\)/)
  assert.match(source, /\[project, locale\]/, 'memoized progress must update on language changes')
  assert.match(source, /kepuSteps\(project.pipeline_mode\)\.map/)
  assert.doesNotMatch(source, /marketplace\/translate|useMarketplaceLocale|MutationObserver|TreeWalker/)
})

test('interpolated user content stays verbatim and helper follows active locale', () => {
  const narration = '标题：保留中文 {number} / original narration'
  assert.equal(storyboardText('｜旁白：{narration}', { narration }, 'en'), ` | Narration: ${narration}`)
  assert.equal(storyboardText('镜头 {number}', { number: 12 }, 'en'), 'Shot 12')
  applyLocale('en', false)
  assert.equal(storyboardText('保存'), 'Save')
  applyLocale('zh', false)
  assert.equal(storyboardText('保存'), '保存')
  assert.match(source, /<h1[^>]*>\{project.title\}<\/h1>/)
  assert.match(source, /\{project.source_text\}/)
  assert.match(source, /value=\{editing.narration\}/)
  assert.match(source, /value=\{promptEdit.style_prompt\}/)
})

test('CSV headers, dynamic summaries, prompts and duration errors have English translations', () => {
  for (const key of ['镜号', '旁白', '画面描述', '时长秒', '状态', '镜头标题', '总时长: {duration} | 画面: {images}/{total} 个 | 视频: {videos}/{total} 段 | 清晰度: {resolution}', '分镜列表（共 {count} 个场景）', '编辑镜头 {number} · {mode}']) {
    assert.doesNotMatch(storyboardText(key, {}, 'en'), han)
  }
  assert.equal(storyboardError('单个 @duration 需在 3–12 秒之间', 'en'), 'Each @duration must be between 3 and 12 seconds')
  assert.equal(storyboardError('镜头时长合计不能超过 30 秒（当前 36s）', 'en'), 'Total shot duration cannot exceed 30 seconds (currently 36s)')
  assert.equal(storyboardError('Custom upstream error: 用户输入', 'en'), 'Custom upstream error: 用户输入')
  assert.match(source, /placeholder=\{st\(SEGMENT_SCRIPT_PLACEHOLDER\)\}/)
  assert.match(source, /msg.includes\('合成成片'\)/, 'API error control-flow discriminator must remain unchanged')
})

test('only known template IDs map names; custom data remains unchanged', () => {
  for (const id of ['anim_3d', 'soft_anime', 'kids_flat', 'ink_guofeng', 'opensource_showcase', 'portrait_story']) {
    assert.doesNotMatch(storyboardTemplateName(id, '原模板名', 'en'), han)
    assert.equal(storyboardTemplateName(id, '原模板名', 'zh'), '原模板名')
  }
  assert.equal(storyboardTemplateName('custom', '用户自定义模板', 'en'), '用户自定义模板')
  assert.equal(storyboardTemplateName('custom', undefined, 'en'), 'custom')
})
