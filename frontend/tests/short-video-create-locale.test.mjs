import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { interpolate } from '../src/i18n/lookup.ts'

const han = /\p{Script=Han}/u
const pagePath = '../src/pages/studio/CreateProjectPage.tsx'
const readSource = path => readFileSync(new URL(path, import.meta.url), 'utf8')

// Load the dependency-free dictionaries without importing the browser i18n graph.
function loadLocale(locale) {
  const source = readSource(`../src/i18n/locales/${locale}/shortVideoCreate.ts`)
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
  const exports = {}
  vm.runInNewContext(outputText, { exports })
  return JSON.parse(JSON.stringify(exports[`${locale}ShortVideoCreate`]))
}

// Flatten arrays as well as objects so missing examples and nested translations fail parity.
function leaves(value, prefix = '') {
  if (typeof value === 'string') return [[prefix, value]]
  assert.ok(value && typeof value === 'object', `${prefix} must contain translated strings`)
  return Object.entries(value).flatMap(([key, child]) => leaves(child, prefix ? `${prefix}.${key}` : key))
}

// Parse TSX to distinguish visible literals from comments and business prompts.
function parsePage() {
  const source = readSource(pagePath)
  return ts.createSourceFile('CreateProjectPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
}

function descendants(node, predicate) {
  const result = []
  function visit(child) {
    if (predicate(child)) result.push(child)
    ts.forEachChild(child, visit)
  }
  visit(node)
  return result
}

function placeholders(text) {
  return [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]))].sort()
}

test('short-video creation dictionaries have identical nonempty bilingual key structures', () => {
  const en = leaves(loadLocale('en'))
  const zh = leaves(loadLocale('zh'))
  assert.deepEqual(en.map(([key]) => key).sort(), zh.map(([key]) => key).sort())
  assert.ok(en.length > 50, 'the complete creation form, not just its header, must be translated')
  for (const [key, value] of [...en, ...zh]) assert.ok(value.trim(), `${key} must not be empty`)
  for (const [key, value] of en) assert.doesNotMatch(value, han, `English ${key} contains Chinese text`)
  assert.ok(zh.some(([, value]) => han.test(value)), 'Chinese translations must remain Chinese')
})

test('all four curated styles and all three clickable examples have real translations', () => {
  for (const locale of ['en', 'zh']) {
    const dictionary = loadLocale(locale)
    assert.deepEqual(Object.keys(dictionary.styles).sort(), ['anim_3d', 'soft_anime', 'kids_flat', 'ink_guofeng'].sort())
    for (const [id, style] of Object.entries(dictionary.styles)) {
      assert.ok(style.name?.trim(), `${locale} ${id} name`)
      assert.ok(style.description?.trim(), `${locale} ${id} description`)
    }
    assert.equal(dictionary.examples.length, 3)
    assert.equal(new Set(dictionary.examples).size, 3)
    assert.ok(dictionary.examples.every(example => typeof example === 'string' && example.trim()))
  }
  assert.notDeepEqual(loadLocale('en').examples, loadLocale('zh').examples)
})

test('step labels include the still-image script/assets/compose path in both languages', () => {
  for (const locale of ['en', 'zh']) {
    const { steps } = loadLocale(locale)
    for (const key of ['script', 'assets', 'compose']) assert.ok(steps[key]?.trim(), `${locale} image_text step ${key}`)
    assert.ok(Object.keys(steps).length >= 4, 'full video pipeline must also have translated steps')
  }
  const page = parsePage()
  const source = page.getFullText()
  assert.match(source, /(?:shortVideoCreate\.steps\s*\[|shortVideoCreate\.steps\.\$\{)/)
  assert.match(source, /<Stepper\b[^>]*steps=\{/)
  assert.doesNotMatch(source, /<Stepper\b[^>]*steps=\{kepuSteps\(pipelineMode\)\}/, 'raw Chinese step labels must not be rendered')
  const mapping = descendants(page, node => ts.isCallExpression(node)
    && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'map'
    && /shortVideoCreate\.steps[.[]/.test(node.getText(page)))[0]
  assert.ok(mapping, 'pipeline steps must map keys to translated labels')
  const expression = ts.transpileModule(`(${mapping.getText(page)})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const paths = { full: ['topic', 'style', 'confirm', 'assets', 'videos', 'compose'], image_text: ['topic', 'confirm', 'assets', 'compose'] }
  for (const locale of ['en', 'zh']) {
    for (const pipelineMode of Object.keys(paths)) {
      const shortVideoCreate = loadLocale(locale)
      const result = vm.runInNewContext(expression, {
        shortVideoCreate, pipelineMode,
        t: path => path.split('.').slice(1).reduce((value, key) => value[key], shortVideoCreate),
        kepuSteps: mode => paths[mode].map(key => ({ key, label: `untranslated-${key}` })),
      })
      assert.deepEqual(JSON.parse(JSON.stringify(result)), paths[pipelineMode].map(key => ({ key, label: (pipelineMode === 'image_text' ? shortVideoCreate.stillSteps : shortVideoCreate.steps)[key] })))
    }
  }
})

test('dynamic message placeholders match in both languages and interpolate without losing values', () => {
  const en = leaves(loadLocale('en'))
  const zh = new Map(leaves(loadLocale('zh')))
  let dynamicCount = 0
  for (const [key, text] of en) {
    const names = placeholders(text)
    assert.deepEqual(names, placeholders(zh.get(key)), `${key} placeholder parity`)
    if (!names.length) continue
    dynamicCount++
    const vars = Object.fromEntries(names.map((name, index) => [name, index === 0 ? 37 : `value-${name}`]))
    for (const template of [text, zh.get(key)]) {
      const rendered = interpolate(template, vars)
      assert.doesNotMatch(rendered, /\{\w+\}/, `${key} has an unresolved placeholder`)
      for (const value of Object.values(vars)) assert.ok(rendered.includes(String(value)), `${key} lost ${value}`)
    }
  }
  assert.ok(dynamicCount >= 3, 'duration, character count and model/reference hints must use interpolation')
  const page = parsePage()
  const calls = descendants(page, node => ts.isCallExpression(node) && node.expression.getText(page) === 't')
    .filter(node => ts.isStringLiteral(node.arguments[0]) && node.arguments[0].text.startsWith('shortVideoCreate.'))
  assert.ok(calls.length >= 3)
  const catalog = new Map(en)
  for (const call of calls) {
    const key = call.arguments[0].text.slice('shortVideoCreate.'.length)
    assert.ok(catalog.has(key), `page references missing message ${key}`)
    const required = placeholders(catalog.get(key))
    if (!required.length) continue
    assert.ok(call.arguments[1] && ts.isObjectLiteralExpression(call.arguments[1]), `${key} must supply interpolation values`)
    const provided = call.arguments[1].properties.map(property => property.name?.getText(page).replace(/['"]/g, ''))
    for (const name of required) assert.ok(provided.includes(name), `${key} must supply ${name}`)
  }
})

test('the page and locale roots wire translated content throughout the form, not only the header', () => {
  for (const locale of ['en', 'zh']) {
    const root = readSource(`../src/i18n/locales/${locale}.ts`)
    assert.match(root, new RegExp(`import\\s*\\{\\s*${locale}ShortVideoCreate\\s*\\}[^\\n]*shortVideoCreate`))
    assert.match(root, new RegExp(`shortVideoCreate:\\s*${locale}ShortVideoCreate`))
  }
  const page = parsePage()
  const source = page.getFullText()
  assert.match(source, /useI18n\(\)/)
  assert.match(source, /m\.shortVideoCreate/)
  const alias = descendants(page, node => ts.isVariableDeclaration(node) && node.initializer?.getText(page) === 'm.shortVideoCreate')[0]?.name.getText(page)
  assert.ok(alias, 'the active locale dictionary must be read inside the page')
  assert.match(source, new RegExp(`${alias}\\.styles\\s*\\[[^\\]]+\\]\\??\\.name`))
  assert.match(source, new RegExp(`${alias}\\.styles\\s*\\[[^\\]]+\\]\\??\\.description`))
  assert.match(source, new RegExp(`${alias}\\.examples\\.map`))
  const jsxRegions = descendants(page, node => ts.isJsxElement(node) && ['header', 'main', 'aside'].includes(node.openingElement.tagName.getText(page)))
  for (const tag of ['header', 'main', 'aside']) {
    const region = jsxRegions.find(node => node.openingElement.tagName.getText(page) === tag)
    assert.ok(region, `missing ${tag} region`)
    assert.match(region.getText(page), new RegExp(`(?:shortVideoCreate|${alias})[.\\[]`), `${tag} must render locale messages`)
    const literals = descendants(region, node => ts.isJsxText(node) || ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))
    for (const literal of literals) assert.doesNotMatch(literal.text, han, `${tag} still contains hardcoded Chinese UI: ${literal.text}`)
  }
  assert.doesNotMatch(source, /\{item\.(?:name|description)\}/, 'backend template names are not localized UI labels')
})

test('UI locale does not rewrite project content or force the narration language', () => {
  const page = parsePage()
  const payload = descendants(page, node => ts.isFunctionDeclaration(node) && node.name?.text === 'payload')[0]
  assert.ok(payload, 'the payload builder must remain inspectable independently of UI text')
  const source = ts.transpileModule(`(${payload.getText(page)})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const mediaSettings = { ratio: '9:16', imageModel: 'image-model', videoModel: 'video-model', imageResolution: '2K', videoResolution: '720p' }
  for (const locale of ['en', 'zh']) {
    for (const pipelineMode of ['full', 'image_text']) {
      const build = vm.runInNewContext(source, { templateId: 'kids_flat', pipelineMode, mediaSettings, ratio: '16:9', duration: 90, voice: 'zh-CN-voice', locale, shortVideoCreate: loadLocale(locale) })
      assert.deepEqual(JSON.parse(JSON.stringify(build('  原始中文旁白 English input  ', '  用户标题  '))), {
        template_id: 'kids_flat', title: '用户标题', source_type: 'script', source_text: '原始中文旁白 English input',
        pipeline_mode: pipelineMode, resolution_mode: 'hd', output_ratio: '9:16', target_duration_sec: 90,
        voice_id: 'zh-CN-voice', image_model: 'image-model', video_model: 'video-model', image_resolution: '2K', video_resolution: '720p',
      })
      assert.equal(build('  原始中文旁白  ', ' ').title, '原始中文旁白')
    }
  }
  const expand = descendants(page, node => ts.isCallExpression(node) && node.expression.getText(page) === 'api.expandContent')[0]
  assert.ok(expand)
  for (const locale of ['en', 'zh']) {
    for (const idea of ['  原始主题  ', '  Why is the sky blue?  ']) {
      const context = { idea, duration: 90, selectedTemplate: { name: '绘本插画' }, locale, shortVideoCreate: loadLocale(locale) }
      const topic = vm.runInNewContext(expand.arguments[0].getText(page), context)
      assert.equal(topic, idea.trim(), 'only original content should determine the output language')
      const options = vm.runInNewContext(`(${expand.arguments[2].getText(page)})`, context)
      assert.deepEqual(JSON.parse(JSON.stringify(options)), { target_duration_sec: 90, style: '绘本插画' })
    }
  }
  assert.equal(expand.arguments[1].text, 'script')
})
