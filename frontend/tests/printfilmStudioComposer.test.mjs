import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('composer menus apply parameters; writing sends configured instructions and updates only its node', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const old = new Map()
  const install = (key, value) => { old.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { configurable: true, writable: true, value }) }
  for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent', 'localStorage']) install(key, dom.window[key])
  install('IS_REACT_ACT_ENVIRONMENT', true)
  const nodeDefaults = {image:'gpt-image-2.5',video:'seedance-2.0',text:'writer-test'}
  localStorage.setItem('printfilm.node-defaults.v1', JSON.stringify(nodeDefaults))
  const requests = []
  let holdStreamOpen=false,cancelledStreams=0
  install('fetch', async (url, init) => {
    requests.push({ url: String(url), body: init?.body && JSON.parse(init.body) })
    if (String(url).endsWith('/agent/config')) return Response.json({ models: [{ id: 'writer-test', label: '测试模型' }] })
    if (String(url).endsWith('/stream') && holdStreamOpen) {
      let timer
      return new Response(new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('{"type":"message_delta","content":"不等断开直接写回"}\n{"type":"done"}\n')); timer=setTimeout(()=>controller.close(),1500)},cancel(){clearTimeout(timer);cancelledStreams++}}))
    }
    if (String(url).endsWith('/stream')) return new Response('{"type":"message_delta","content":"第一幕：晨光。"}\n{"type":"done"}\n')
    return Response.json({ id: 'session-test' })
  })
  let server, root
  try {
    server = await createServer({ configFile: false, cacheDir: '.tmp/vite-composer-tests', optimizeDeps: { noDiscovery: true, include: [] }, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
    const { PromptComposer } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/PromptComposer.tsx')
    const { InlineTextComposer } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/InlineTextComposer.tsx')
    const { VideoNodeSetup } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/VideoNodeSetup.tsx')
    const { createElement: h, act, useState } = await import('react')
    const { createRoot } = await import('react-dom/client')
    root = createRoot(document.getElementById('root'))
    const click = async (element) => { assert.ok(element); await act(async () => element.dispatchEvent(new MouseEvent('click', { bubbles: true }))) }
    const button = (label) => document.querySelector(`button[aria-label="${label}"]`)
    const byText = (text) => [...document.querySelectorAll('button')].find((item) => item.textContent === text)
    const selected = {}
    const noop = () => {}
    const props = { action: 'video', prompt: '测试', onPrompt: noop, chips: [], onRemoveChip: noop, onAddChip: (chip, text) => { selected.preset = text }, refs: [], onRemoveRef: noop, onAddRef: noop, mentions: { connected: [], canvas: [], assets: [] }, onMention: noop, modelId: 'm', modelOptions: [{ id: 'm', label: '模型 M' }], onModelChange: noop, ratio: '16:9', onRatioChange: (v) => { selected.ratio = v }, count: '1', onCountChange: (v) => { selected.count = v }, resolution: '720p', onResolutionChange: (v) => { selected.resolution = v }, duration: '5', onDurationChange: (v) => { selected.duration = v }, estimate: '0.5 元 / 秒', generateAudio: true, onAudioChange: value => { selected.audio = value }, isVideo: true, videoMode: 'text_to_video', videoModeOptions: [{ id: 'text_to_video', label: '文生视频' }, { id: 'first_last_frame', label: '首尾帧' }], onVideoModeChange: (v) => { selected.mode = v }, onClose: noop, onSubmit: noop, canSubmit: true }
    const pendingRefs=[{id:'role',label:'角色参考图',url:'',mediaKind:'image',status:'待生成'},{id:'writer',label:'分镜提示词',url:'',mediaKind:'text',status:'生成中'},{id:'clip',label:'参考视频',url:'',mediaKind:'video',status:'待生成'}]
    await act(async()=>root.render(h(PromptComposer,{...props,refs:pendingRefs})))
    for(const ref of pendingRefs) assert.ok(document.querySelector('.pf-composer-card').textContent.includes(ref.label))
    assert.equal(document.querySelectorAll('.pf-chip.is-ref.is-pending').length,3)
    assert.equal(document.querySelectorAll('.pf-chip.is-ref img').length,0)
    await act(async()=>root.render(h(PromptComposer,{...props,refs:[{...pendingRefs[0],url:'/ready.png',status:''}]})))
    assert.ok(document.querySelector('.pf-chip.is-ref img')?.getAttribute('src').includes('/ready.png'))
    const pickedReferences = []
    const choices = Array.from({ length: 5 }, (_, i) => ({ id: `ref-${i}`, source: 'node', label: `参考 ${i}`, url: `/ref-${i}.png`, mediaKind: 'image' }))
    function ReferenceComposer() {
      const [prompt, setPrompt] = useState('保留原有描述')
      const [refs, setRefs] = useState([])
      return h(PromptComposer, { ...props, action: 'edit', isVideo: false, prompt, refs,
        mentions: { connected: refs, canvas: choices.filter(item => !refs.some(ref => ref.id === item.id)), assets: [] },
        onPrompt: setPrompt, onMention: item => { pickedReferences.push(item.id); setRefs(current => [...current, item]) },
      })
    }
    await act(async () => root.render(h(ReferenceComposer)))
    for (const choice of choices) {
      const input = document.querySelector('[aria-label="生成描述"]')
      const trigger = [...document.querySelectorAll('button')].find(item => item.textContent.trim() === '参考图')
      await act(async () => {
        input.focus()
        const down = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
        trigger.dispatchEvent(down)
        assert.equal(down.defaultPrevented, true, 'reference button must not blur the prompt')
        // Also cover a delayed blur left by a previous focus transition.
        input.blur()
        trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 160)) })
      assert.ok(document.querySelector('[role="listbox"]'), 'reference menu stays open past the blur timeout')
      const option = [...document.querySelectorAll('.pf-mention button')].find(item => item.querySelector('b')?.textContent === choice.label)
      await click(option)
      assert.equal(document.querySelector('[role="listbox"]'), null)
    }
    assert.equal(document.querySelectorAll('.pf-chip.is-ref').length, 5)
    assert.deepEqual(pickedReferences, choices.map(item => item.id))
    assert.ok(document.querySelector('[aria-label="生成描述"]').textContent.startsWith('保留原有描述'))
    await act(async () => root.render(h(PromptComposer, props)))
    await click(button('视频生成方式')); await click(byText('首尾帧'))
    assert.equal(selected.mode, 'first_last_frame'); assert.equal(document.querySelector('[role="dialog"]'), null)
    await click(button('视频参数')); await click(byText('9:16')); await click(byText('1080p')); await click(byText('8 秒'))
    assert.equal(document.querySelector('.pf-composer-audio input').checked,true)
    await click(document.querySelector('.pf-composer-audio input')); assert.equal(selected.audio,false)
    assert.deepEqual([selected.ratio, selected.resolution, selected.duration], ['9:16', '1080p', '8'])
    await act(async () => document.querySelector('[role="dialog"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    assert.equal(document.activeElement, button('视频参数'))
    await click(byText('运镜')); await click([...document.querySelectorAll('.pf-prompt-presets button')][0]); assert.match(selected.preset, /推进/)
    await act(async () => root.render(h(PromptComposer, { ...props, action: 'edit', isVideo: false })))
    await click(button('张数')); await click(byText('4 张')); assert.equal(selected.count, '4')
    const { PromptInput } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/PromptInput.tsx')
    const { mentionToken, readPromptDom } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/promptMentions.ts')
    const reference = { id: 'source-image', source: 'node', label: '首帧', url: '/test.png', mediaKind: 'image' }
    const richPrompt = `保持 ${mentionToken(reference)} 的人物一致`
    let editedPrompt
    await act(async () => root.render(h(PromptInput, { value: richPrompt, label: '生成描述', references: [reference], onChange: (value) => { editedPrompt = value } })))
    const input = document.querySelector('[aria-label="生成描述"]')
    assert.equal(input.querySelector('.pf-inline-reference img').getAttribute('src'), '/test.png')
    assert.equal(input.querySelector('.pf-inline-reference').contentEditable, 'false')
    assert.equal(readPromptDom(input), richPrompt, 'thumbnail markup serializes to its stable token')
    await act(async () => { input.append(document.createTextNode('，缓慢推进')); input.dispatchEvent(new Event('input', { bubbles: true })) })
    assert.equal(editedPrompt, `${richPrompt}，缓慢推进`)
    await act(async () => { input.querySelector('.pf-inline-reference').remove(); input.dispatchEvent(new Event('input', { bubbles: true })) })
    assert.equal(editedPrompt, '保持  的人物一致，缓慢推进', 'removing the atomic chip removes the token')
    let chosen
    await act(async () => root.render(h(VideoNodeSetup, { mode: 'first_last_frame', initialIds: ['connected-script'], items: [{ id: 'a', label: 'A', url: 'a.png' }, { id: 'b', label: 'B', url: 'b.png' }], onApply: (ids) => { chosen = ids }, onCreate: noop, onLibrary: noop, onClose: noop })))
    assert.equal(byText('完成 / 返回视频节点').disabled, true)
    await click(byText('B')); await click(byText('A')); await click(byText('完成 / 返回视频节点')); assert.deepEqual(chosen, ['b', 'a'])
    const busy = [], applied = []
    await act(async () => root.render(h(InlineTextComposer, { projectId: 1, nodeId: 'script-1', title: '故事脚本', text: '原正文', settings: { writingPrompt: '写开场', writingType: '分镜脚本', writingSkill: 'acting' }, references: [{ id: 'ref-1', label: '角色', text: '小明' }], candidates: [], headers: {}, writable: true, onSetting: noop, onReference: noop, onBusy: (value) => busy.push(value), onApply: (...args) => applied.push(args) })))
    await click(button('开始 AI 写作'))
    assert.deepEqual(applied, [['第一幕：晨光。', '原正文']]); assert.ok(busy.includes(true)); assert.equal(busy.at(-1), false)
    const request = requests.find((item) => item.url.endsWith('/stream')).body
    assert.match(request.prompt, /分镜脚本/); assert.match(request.prompt, /标注说话者/)
    assert.deepEqual(request.node_defaults, nodeDefaults, 'Agent requests carry browser defaults to server-side node creation')
    assert.deepEqual(request.node_ids, ['script-1', 'ref-1']); assert.deepEqual(request.enabled_tools, [])
    const outputs = [{ id:'video',label:'镜头1',kind:'video',model:'video-model',ratio:'9:16',duration:'8' }]
    const writingProps = { projectId:1,nodeId:'writer',title:'镜头提示词',text:'旧提示词',settings:{writingPrompt:'角色抬头，约5秒，16:9。'}, references:[{id:'role',label:'角色',text:'角色外貌',url:'/role.png',mediaKind:'image'}],candidates:[],headers:{},writable:true,outputs,onSetting:noop,onReference:noop,onBusy:noop,onApply:(...args)=>applied.push(args),onRunDependencies:()=>{throw Error('completed writer must regenerate instead of being skipped')} }
    await act(async()=>root.render(h(InlineTextComposer,writingProps)))
    assert.equal(document.querySelector('[aria-label="AI 写作要求"] .pf-inline-reference img').getAttribute('src'),'/role.png')
    assert.match(document.querySelector('[aria-label="AI 写作要求"]').textContent,/约 8 秒，9:16/)
    assert.match(document.querySelector('[aria-label="下游生成参数"]').textContent,/video-model.*9:16.*8 秒/)
    await click(button('开始 AI 写作'))
    assert.deepEqual(applied.at(-1)[2],outputs)
    assert.match(applied.at(-1)[0],/\(node:role\)/,'generated output retains a resolvable image identity even when the model omits it')
    const { PromptText } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/PromptText.tsx')
    await act(async()=>root.render(h(PromptText,{value:applied.at(-1)[0],references:[{...writingProps.references[0],source:'node'}]})))
    assert.equal(document.querySelector('.pf-inline-reference img').getAttribute('src'),'/role.png')
    assert.match(requests.filter(item=>item.url.endsWith('/stream')).at(-1).body.prompt,/比例 9:16，时长 8 秒/)
    await act(async()=>root.render(h(InlineTextComposer,{...writingProps,references:[{...writingProps.references[0],url:'/updated.png'}]})))
    assert.equal(document.querySelector('[aria-label="AI 写作要求"] .pf-inline-reference img').getAttribute('src'),'/updated.png','regenerated thumbnail refreshes without text change')
    const prior=requests.filter(item=>item.url.endsWith('/stream')).length
    await act(async()=>root.render(h(InlineTextComposer,{...writingProps,text:'',settings:{writingPrompt:'参考现有角色写提示词',deferredPrompt:true},references:[{id:'pending-image',label:'尚未生成的角色',text:'身份设定',mediaKind:'image'}],onRunDependencies:()=>{throw Error('single text run must not generate upstream nodes')}})))
    await click(button('开始 AI 写作'))
    assert.equal(requests.filter(item=>item.url.endsWith('/stream')).length,prior+1,'empty deferred text still executes only its own writing request')
    assert.deepEqual(requests.filter(item=>item.url.endsWith('/stream')).at(-1).body.enabled_tools,[],'text writing cannot submit media or canvas tools')
    holdStreamOpen=true
    await click(button('开始 AI 写作'))
    assert.match(applied.at(-1)[0],/^不等断开直接写回\n参考图片：.*\(node:pending-image\)/)
    assert.equal(cancelledStreams,1,'done event ends writing without waiting for a persistent HTTP connection')
    assert.equal(button('停止写作'),null)

    const linkedByMention = []
    const extraReference = { id:'new-image',label:'新参考',text:'',url:'/new.png',mediaKind:'image' }
    function WritingMentions() {
      const [settings,setSettings] = useState({writingPrompt:'在飞机上跳舞@后续正文'})
      const [references,setReferences] = useState(writingProps.references)
      return h(InlineTextComposer,{...writingProps,nodeId:'mentions',outputs:[],settings,references,candidates:[...writingProps.references,extraReference],
        onSetting:(key,value)=>setSettings(current=>({...current,[key]:value})),
        onReference:id=>{linkedByMention.push(id);setReferences(current=>[...current,extraReference])},
      })
    }
    await act(async()=>root.render(h(WritingMentions)))
    const writingInput = document.querySelector('[aria-label="AI 写作要求"]')
    await act(async()=>{
      writingInput.focus()
      const range=document.createRange();range.setStart(writingInput.firstChild,'在飞机上跳舞@'.length);range.collapse(true)
      window.getSelection().removeAllRanges();window.getSelection().addRange(range)
      writingInput.dispatchEvent(new KeyboardEvent('keyup',{key:'@',bubbles:true}))
    })
    assert.match(document.querySelector('.pf-mention').textContent,/已接入/)
    await click([...document.querySelectorAll('.pf-mention button')].find(item=>item.textContent.includes('角色')))
    assert.match(readPromptDom(writingInput),/在飞机上跳舞@\[.*\]\(node:role\) 后续正文/)
    assert.deepEqual(linkedByMention,[],'mentioning an existing reference must not disconnect it')
    await act(async()=>{
      writingInput.textContent='继续@新'
      const range=document.createRange();range.selectNodeContents(writingInput);range.collapse(false)
      window.getSelection().removeAllRanges();window.getSelection().addRange(range)
      writingInput.dispatchEvent(new Event('input',{bubbles:true}))
    })
    await click([...document.querySelectorAll('.pf-mention button')].find(item=>item.textContent.includes('新参考')))
    assert.deepEqual(linkedByMention,['new-image'])
    assert.match(readPromptDom(writingInput),/\(node:new-image\)/)
    assert.equal(document.querySelector('.pf-mention'),null)



  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close(); dom.window.close()
    for (const [key, descriptor] of old) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key] }
  }
})
