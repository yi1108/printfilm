import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/canvasNodeMedia.ts', import.meta.url), 'utf8')
const sandbox = { exports: {}, require: () => ({}) }
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, sandbox)
const { videoPosterUrl } = sandbox.exports

test('视频和音频地址不能充当视频封面，包含签名查询和大小写扩展名', () => {
  for (const url of [undefined, null, '', '/old.mp4', 'https://cdn.test/movie.MP4?token=1#t=2', '/movie.mp4?filename=cover.jpg', '/movie.mp4#cover.png', '/movie.webm', '/movie.mov', '/playlist.m3u8', '/voice.mp3', '/unknown']) {
    assert.equal(videoPosterUrl(url), undefined)
  }
})

test('保留图片封面、签名图片和内嵌图片', () => {
  for (const url of ['/new.jpg', 'https://cdn.test/frame.PNG?token=1#preview', '/cover.webp', '/cover.avif', 'data:image/svg+xml,<svg/>', 'data:image/png;base64,aGVsbG8=']) {
    assert.equal(videoPosterUrl(url), url)
  }
})
