import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { applyLocale } from '../src/i18n/detect.ts'
import { studioSecondaryEnglish, studioSecondaryText as text } from '../src/i18n/studioSecondaryText.ts'

const pages = ['EditorPage', 'StyleConfigPage', 'ImageTextStoryboard']
const readPage = name => readFileSync(new URL(`../src/pages/studio/${name}.tsx`, import.meta.url), 'utf8')
const placeholders = value => [...value.matchAll(/\{\d+\}/g)].map(match => match[0]).sort()

// Validate the entire independent dictionary, including dynamic counters and price units.
test('secondary studio dictionary has complete English and matching interpolations', () => {
  assert.ok(Object.keys(studioSecondaryEnglish).length > 150)
  for (const [zh, en] of Object.entries(studioSecondaryEnglish)) {
    assert.ok(en.trim(), zh)
    assert.doesNotMatch(en, /\p{Script=Han}/u, zh)
    assert.deepEqual(placeholders(en), placeholders(zh), zh)
    assert.equal(text(zh, [], 'zh'), zh)
    assert.equal(text(zh, [], 'en'), en)
  }
})

// Locale changes must resolve at render time, without mutating interpolated user data.
test('active locale switching preserves user text and unknown API messages', () => {
  const userContent = '用户的中文标题 {1} prompt'
  applyLocale('en', false)
  assert.equal(text('试听「{0}」', [userContent]), `Preview “${userContent}”`)
  assert.equal(text(userContent), userContent)
  assert.equal(text('Unknown API error'), 'Unknown API error')
  applyLocale('zh', false)
  assert.equal(text('试听「{0}」', [userContent]), `试听「${userContent}」`)
  applyLocale('en', false)
  assert.equal(text('镜头 {0}', [12]), 'Shot 12')
  applyLocale('zh', false)
})

// Parse JSX rather than comments/internal tab keys to catch UI omissions.
test('all scoped pages subscribe to locale and translate visible Chinese literals', () => {
  for (const name of pages) {
    const source = readPage(name)
    assert.match(source, /useMarketplaceLocale\(\)/)
    assert.doesNotMatch(source, /MutationObserver|document\.body|TreeWalker/)
    const ast = ts.createSourceFile(`${name}.tsx`, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    function visit(node) {
      if (ts.isJsxText(node)) assert.doesNotMatch(node.text, /\p{Script=Han}/u, `${name}: ${node.text}`)
      if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)) {
        assert.doesNotMatch(node.initializer.text, /\p{Script=Han}/u, `${name}: attribute ${node.name.getText(ast)}`)
      }
      if (ts.isCallExpression(node) && node.expression.getText(ast) === 'mt' && ts.isStringLiteral(node.arguments[0])) {
        assert.ok(studioSecondaryEnglish[node.arguments[0].text], `${name}: missing ${node.arguments[0].text}`)
      }
      ts.forEachChild(node, visit)
    }
    visit(ast)
  }
})

test('user-authored content stays outside translation calls and request payloads remain raw', () => {
  const editor = readPage('EditorPage')
  const style = readPage('StyleConfigPage')
  const board = readPage('ImageTextStoryboard')
  assert.match(editor, /updateShot\(project\.id, shot\.id, \{ narration \}\)/)
  assert.match(editor, /<strong>\{project\.title\}<\/strong>/)
  assert.match(style, /style_prompt: sameStyle \? '' : styleOut/)
  assert.match(style, /extra_prompt: sameExtra \? '' : extraOut/)
  for (const source of [editor, style, board]) {
    assert.doesNotMatch(source, /mt\((?:project\.title|shot\.narration|shot\.img_prompt|stylePrompt|extraPrompt)/)
  }
  assert.match(board, /<p>\{project\.source_text\}<\/p>/)
  assert.match(board, /scenePromptForDisplay\(shot\.img_prompt\)/)
})
