/** Separate speakable text from directing prose before sending a video prompt. */
export function videoPromptAudio(prompt: string, model = '') {
  const lines: string[] = []
  const picture = prompt.replace(/[“「"]([^”」"\n]+)[”」"]/g, (quoted, words: string, offset: number) => {
    const context = prompt.slice(0, offset).split(/[。！？\n”」"]/).at(-1)?.slice(-80) || ''
    // Quotes used for visual labels or cinematography are never dialogue.
    const cue = /(?:台词|对白|旁白|独白)[：:（(]|(?:喊出|喊道|说道|问道|答道|回答|低语|嘶喊|吼道|呼喊|说|问|喊|念道)[：:]?\s*$/.test(context.trim())
    if (!cue || /(?:不要|禁止|不说|不得).*(?:台词|说|喊)/.test(context)) return quoted
    lines.push(words)
    return `〔发声台词${lines.length}，原文见声音区〕`
  })
  const seedance25 = /^(?:doubao-)?seedance-2[.-]5(?:-\d{6})?$/i.test(model)
  const speech = lines.length ? '唯一允许发声的台词（保持上方说话人对应；每句只说一次）：\n' + lines.map((line,index)=>
    `台词${index+1}：${seedance25 ? '{' : ''}“${line}”${seedance25 ? '}' : ''}`).join('\n') : '本镜没有指定台词：不生成对白、旁白或可辨识的人声语言。'
  return `拍摄指令（只执行，不朗读，不显示为字幕）：\n${picture}\n\n声音执行区：\n${speech}\n画面、运镜、动作、表演方式、参考素材说明和环境声描述均不得念出或转为旁白。环境声只还原声音，不朗读其名称；不得添加未指定的台词、配乐或解说。`
}
