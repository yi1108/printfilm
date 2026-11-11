/** 仅本地化脚本协议标记；正文与持久化协议保持原样。 */
const CUE_PAIRS: readonly (readonly [string, string])[] = [
  ['【旁白·自然语速·同步字幕】', '【Narration · Natural pace · Synced subtitles】'],
  ['【旁白·慢速清晰·同步字幕】', '【Narration · Slow and clear · Synced subtitles】'],
  ['【对白·慢速清晰·同步字幕】', '【Dialogue · Slow and clear · Synced subtitles】'],
  ['【画面·无配音仅环境音】', '【Visual · Ambient sound only】'],
  ['【空镜·可仅环境音与 BGM】', '【Establishing shot · Ambient sound and BGM】'],
]

/** 英文界面展示协议标签，不翻译用户输入或模板内容。 */
export function displaySegmentCues(script: string, locale: string): string {
  if (locale !== 'en') return script
  let result = script
  for (const [source, target] of CUE_PAIRS) result = result.replaceAll(source, target)
  return result.replaceAll('【字幕：', '【Subtitles: ').replaceAll('【BGM：', '【BGM: ')
}

/** 编辑输入还原为解析器认可的协议，避免保存时丢失旁白。 */
export function canonicalSegmentCues(script: string): string {
  let result = script
  for (const [source, target] of CUE_PAIRS) result = result.replaceAll(target, source)
  return result.replaceAll('【Subtitles: ', '【字幕：').replaceAll('【BGM: ', '【BGM：')
}
