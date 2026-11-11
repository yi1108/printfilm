"""Recover story relationships from existing canvas content without model calls."""
import re
from copy import deepcopy

from app.printfilm_studio.canvas.codec import decode_canvas_document


def clean_name(value):
    return re.split(r'[·\n（(]', str(value).strip('【】[] #\n'))[0].strip('【】[] ')


def scene_sections(text):
    pattern = r'(?m)^[ \t【#]*(?:场景[一二三四五六七八九十百\d]+|场[一二三四五六七八九十百\d]+|第[一二三四五六七八九十百\d]+场)[：:]\s*([^\n】]+)'
    matches = list(re.finditer(pattern, text))
    scenes = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        name = re.split(r'\s*[-—]\s*', heading)[0].strip()
        body = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        descriptions = re.findall(r'[（(]([^）)]+)[）)]', body)
        environment = '；'.join(descriptions[:2]) or body[:400]
        scenes.append({'name': name, 'description': body, 'prompt': f'场景参考图：{heading}。环境依据：{environment}。空场景，无主要角色、无字幕。保持原剧本的时代背景，与角色参考图的视觉风格一致。'})
    return scenes


def repair_story_graph(document, script_id):
    from app.printfilm_studio.agent.story_workflow import build_story_plan, _id
    candidate = deepcopy(document)
    nodes = candidate['nodes']
    script = next((node for node in nodes if node['id'] == script_id), None)
    if not script or script.get('type') not in {'script', 'text'} or not script.get('data', {}).get('text'):
        raise ValueError('请选择有正文的剧本节点')
    script_text = script['data']['text']
    unique_script = len([node for node in nodes if node.get('type') == 'script']) == 1
    connected = {edge['target'] for edge in candidate['edges'] if edge['source'] == script_id}
    def belongs(node):
        owner = node.get('data', {}).get('sourceScriptId')
        return owner == script_id or not owner and (node['id'] in connected or unique_script)
    scenes = scene_sections(script_text)
    assets = []
    for node in nodes:
        if node.get('type') not in {'character', 'scene'} or not belongs(node):
            continue
        data = node['data']
        name = clean_name(data.get('label', ''))
        if not name or not data.get('sourceScriptId') and name not in script_text:
            continue
        data.update(sourceScriptId=script_id, storyKind=node['type'])
        assets.append({'kind': node['type'], 'name': name, 'prompt': str(data.get('prompt') or data.get('text') or name), 'description': str(data.get('text') or '')})
    for scene in scenes:
        if not any(item['kind'] == 'scene' and clean_name(item['name']) == clean_name(scene['name']) for item in assets):
            assets.append({'kind': 'scene', **scene})
    if not assets:
        raise ValueError('未找到可复用角色或明确场景，请先抽取角色与场景')
    candidate, _ = build_story_plan(candidate, 'plan_story_assets', {'script_node_id': script_id, 'assets': assets})
    nodes = candidate['nodes']
    refs = [node for node in nodes if node['data'].get('sourceScriptId') == script_id and node['data'].get('storyKind') in {'character', 'scene'}]
    # Existing text prompts remain the source of truth; the repair only restores edges.
    pairs = {(edge['source'], edge['target']) for edge in candidate['edges']}
    def connect(source, target):
        if (source, target) not in pairs:
            candidate['edges'].append({'id': f'{source}->{target}', 'source': source, 'target': target})
            pairs.add((source, target))
    def references(body, scene_name=''):
        selected = [node['id'] for node in refs if clean_name(node['data'].get('label', '')) in body or node['data'].get('storyKind') == 'scene' and clean_name(node['data'].get('label', '')) == clean_name(scene_name)]
        if any(word in body for word in ('三人', '三兄弟')):
            selected += [node['id'] for node in refs if node['data'].get('storyKind') == 'character' and clean_name(node['data'].get('label', '')) in script_text]
        return list(dict.fromkeys(selected))
    outlines = [node for node in nodes if belongs(node) and node.get('type') == 'storyboard' and node['data'].get('text')]
    outlines.sort(key=lambda node: next((index for index, scene in enumerate(scenes) if scene['name'] in node['data']['text'].splitlines()[0]), 999))
    offset = max([int(node['data'].get('shotIndex') or 0) for node in nodes if node['data'].get('sourceScriptId') == script_id and node['data'].get('storyKind') == 'shot_prompt'] or [0])
    shots = []
    for outline in outlines:
        body = outline['data']['text']
        headings = list(re.finditer(r'(?m)^[ \t★#*-]*(?:镜头|分镜)\s*(\d+)[：:]([^\n]+)', body))
        blocks = [(match.group(2).strip(), body[match.start():headings[index + 1].start() if index + 1 < len(headings) else len(body)].strip()) for index, match in enumerate(headings)] or [(str(outline['data'].get('label') or '分镜'), body)]
        scene_name = next((scene['name'] for scene in scenes if scene['name'] in body.splitlines()[0]), '')
        for name, block in blocks:
            ids = references(block, scene_name)
            if not ids:
                continue  # Never guess a foreign scene or connect unrelated images.
            offset += 1
            shots.append({'index': offset, 'name': f'{scene_name} · {name}' if scene_name else name, 'description': block, 'prompt': block, 'reference_node_ids': ids})
        outline['type'] = 'text'
        outline['data'].update(sourceScriptId=script_id, storyKind='shot_outline', originalNodeType='storyboard')
    # Upgrade the previous image-shot format without removing generated images.
    for old in list(nodes):
        data = old['data']
        if data.get('sourceScriptId') != script_id or data.get('storyKind') != 'shot':
            continue
        index = int(data.get('shotIndex') or offset + 1)
        offset = max(offset, index)
        ids = [value for value in data.get('referenceNodeIds', []) if any(ref['id'] == value for ref in refs)]
        ids = ids or references(str(data.get('prompt') or data.get('text') or ''))
        if not ids:
            continue
        shots.append({'index': index, 'name': str(data.get('label') or f'分镜 {index}'), 'description': str(data.get('shotDescription') or data.get('text') or data.get('prompt')), 'prompt': str(data.get('prompt') or data.get('text')), 'reference_node_ids': ids})
        data['storyKind'] = 'shot_reference'
    if shots:
        candidate, _ = build_story_plan(candidate, 'plan_story_shots', {'script_node_id': script_id, 'shots': shots})
    # Restore deleted video partners from current text without rewriting it.
    missing = []
    for prompt in candidate['nodes']:
        data = prompt['data']
        if data.get('sourceScriptId') != script_id or data.get('storyKind') != 'shot_prompt':
            continue
        if not any(node['data'].get('promptNodeId') == prompt['id'] for node in candidate['nodes']):
            missing.append({'index': int(data['shotIndex']), 'name': str(data.get('label') or '分镜'),
                            'description': str(data.get('shotDescription') or data['text']), 'prompt': data['text'],
                            'reference_node_ids': data.get('referenceNodeIds') or references(data['text']),
                            **{key: data[key] for key in ('episodeId', 'episodeNumber', 'episodeTitle') if key in data}})
    if missing:
        candidate, _ = build_story_plan(candidate, 'plan_story_shots', {'script_node_id': script_id, 'shots': missing})
    by_id = {node['id']: node for node in candidate['nodes']}
    pairs = {(edge['source'], edge['target']) for edge in candidate['edges']}
    for prompt in list(candidate['nodes']):
        data = prompt['data']
        if data.get('sourceScriptId') != script_id or data.get('storyKind') != 'shot_prompt':
            continue
        video_id = _id(script_id, 'shot_video', str(data['shotIndex']))
        video = next((node for node in candidate['nodes'] if node['data'].get('promptNodeId') == prompt['id'] and node['data'].get('storyKind') == 'shot_video'), None) or by_id.get(video_id)
        if video:
            video_id = video['id']
            connect(prompt['id'], video_id)
            for ref in video['data'].get('referenceNodeIds', []):
                if ref in by_id:
                    connect(ref, video_id)
                    connect(ref, prompt['id'])
    candidate['edges'] = [edge for edge in candidate['edges'] if script_id not in (edge['source'], edge['target'])]
    from app.printfilm_studio.agent.story_layout import group_story_nodes
    return decode_canvas_document(group_story_nodes(candidate, script_id))
