"""Keep the speech allowlist separate from visual/directing instructions."""
import re


def video_prompt_audio(prompt, model=''):
    lines = []

    def quote(match):
        context = re.split(r'[。！？\n”」"]', prompt[:match.start()])[-1][-80:].strip()
        cue = re.search(r'(?:台词|对白|旁白|独白)[：:（(]|(?:喊出|喊道|说道|问道|答道|回答|低语|嘶喊|吼道|呼喊|说|问|喊|念道)[：:]?\s*$', context)
        if not cue or re.search(r'(?:不要|禁止|不说|不得).*(?:台词|说|喊)', context):
            return match[0]
        lines.append(match[1])
        return f'〔发声台词{len(lines)}，原文见声音区〕'

    picture = re.sub(r'[“「"]([^”」"\n]+)[”」"]', quote, prompt)
    seedance25 = re.fullmatch(r'(?:doubao-)?seedance-2[.-]5(?:-\d{6})?', model or '', re.I)
    if lines:
        speech = '唯一允许发声的台词（保持上方说话人对应；每句只说一次）：\n' + '\n'.join(
            f'台词{i+1}：' + ('{' if seedance25 else '') + f'“{line}”' + ('}' if seedance25 else '') for i, line in enumerate(lines))
    else:
        speech = '本镜没有指定台词：不生成对白、旁白或可辨识的人声语言。'
    return f'拍摄指令（只执行，不朗读，不显示为字幕）：\n{picture}\n\n声音执行区：\n{speech}\n画面、运镜、动作、表演方式、参考素材说明和环境声描述均不得念出或转为旁白。环境声只还原声音，不朗读其名称；不得添加未指定的台词、配乐或解说。'
