"""Bind shot-writing requirements to stable references and concrete video settings."""
import math
import re
from urllib.parse import quote


def shot_parameters(item, script_data):
    prose = str(item.get('prompt') or '') + '\n' + str(item.get('description') or '')
    durations = set(re.findall(r'(?:时长\s*[:：]?\s*|约\s*)(\d+(?:\.\d+)?)\s*(?:秒|s\b)', prose))
    if not durations:
        durations = set(re.findall(r'(\d+(?:\.\d+)?)\s*(?:秒|s\b)', prose))
    duration = item.get('duration', item.get('duration_sec'))
    if duration is None:
        duration = next(iter(durations)) if len(durations) == 1 else script_data.get('videoDuration') or 15
    try:
        seconds = float(str(duration).removesuffix('秒').removesuffix('s').strip())
    except (ValueError, TypeError):
        raise ValueError('分镜时长必须为秒数')
    if isinstance(duration, bool) or not math.isfinite(seconds) or not 0 < seconds <= 15:
        raise ValueError('分镜片段时长必须大于 0 且不超过 15 秒；超长内容请在自然叙事边界拆分，不要截断对白')
    ratios = set(re.findall(r'(?<!\d)(\d{1,2})\s*[:：]\s*(\d{1,2})(?!\d)', prose))
    ratio = str(item.get('ratio') or item.get('aspect_ratio') or (':'.join(next(iter(ratios))) if len(ratios) == 1 else script_data.get('videoRatio') or '16:9')).strip().replace('：', ':')
    if not re.fullmatch(r'[1-9]\d?:[1-9]\d?', ratio):
        raise ValueError('分镜比例必须为明确的宽高比，例如 16:9 或 9:16')
    return {'duration': format(seconds, 'g'), 'ratio': ratio}


def reference_writing_prompt(prompt, ids, existing, parameters=None, description=""):
    from .story_workflow import writing_requirements
    references = []
    for identity in ids:
        label = str(existing[identity].get('data', {}).get('label') or identity)
        references.append(f'@[{quote(label, safe="")}](node:{quote(identity, safe="")})')
    if parameters:
        prompt = f"镜头时长：{parameters['duration']} 秒，画幅：{parameters['ratio']}。\n" + description + '\n' + prompt
    return writing_requirements(prompt, True) + '\n参考图片：' + '、'.join(references)
