"""Stable, paired story groups. Repeated planning preserves user content/media."""
from copy import deepcopy


def _dimension(node, axis, fallback):
    value = node.get(axis) or node.get('style', {}).get(axis) or node.get('measured', {}).get(axis)
    return float(value) if isinstance(value, (int, float)) and value > 0 else fallback


def _episode(node, script, by_id):
    for data in (node.get('data', {}), by_id.get(node.get('parentId'), {}).get('data', {}), script.get('data', {})):
        number = data.get('episodeNumber') or data.get('episode_number')
        if number:
            return f'episode-{number}', f'第{number}集', {'episodeNumber': number}
        identity = data.get('episodeId') or data.get('episode_id')
        if identity:
            return f'episode-id-{identity}', str(data.get('episodeTitle') or f'分集 {identity}'), {'episodeId': identity}
    return '', '', {}


def group_story_nodes(document, script_id, *, shots_only=False):
    by_id = {node['id']: node for node in document['nodes']}
    script = by_id[script_id]
    episodes = {_episode(node, script, by_id)[0] for node in document['nodes'] if node.get('data', {}).get('sourceScriptId') == script_id and node['data'].get('storyKind') in {'character', 'scene', 'shot_video'}}
    result = document
    offset = 0
    for episode in sorted(episodes, key=lambda value: (len(value), value)):
        result = _group_story_episode(result, script_id, episode, offset, shots_only=shots_only)
        frames = [node for node in result['nodes'] if node.get('type') == 'group' and node.get('data', {}).get('sourceScriptId') == script_id and _episode(node, script, {n['id']: n for n in result['nodes']})[0] == episode]
        offset += max([_dimension(frame, 'height', 400) for frame in frames] or [400]) + 160
    return result


def _group_story_episode(document, script_id, episode, offset, *, shots_only=False):
    from app.printfilm_studio.agent.story_workflow import _id, writing_requirements
    result = deepcopy(document)
    nodes, edges = result['nodes'], result['edges']
    by_id = {node['id']: node for node in nodes}
    script = by_id[script_id]
    title = str(script['data'].get('label') or '故事').strip('《》')
    pairs = {(edge['source'], edge['target']) for edge in edges}
    categories = [] if shots_only else [('character', '角色参考', ''), ('scene', '场景参考', '')]
    shot_nodes = sorted((node for node in nodes if node.get('data', {}).get('sourceScriptId') == script_id and node['data'].get('storyKind') == 'shot_video' and _episode(node, script, by_id)[0] == episode), key=lambda node: int(node['data'].get('shotIndex') or 0))
    scene_keys = []
    legacy_numbers = {}
    for node in shot_nodes:
        scene_id = str(node['data'].get('sceneNodeId') or '')
        number = node['data'].get('sceneNumber') or legacy_numbers.get(scene_id) or max([key[0] for key in scene_keys] or [0]) + 1
        legacy_numbers[scene_id] = number
        node['data']['sceneNumber'] = number
        prompt = by_id.get(node['data'].get('promptNodeId'))
        if prompt:
            prompt['data']['sceneNumber'] = number
        if (number, scene_id) not in scene_keys:
            scene_keys.append((number, scene_id))
    categories = [(kind, prefix, scene_id, None) for kind, prefix, scene_id in categories]
    categories += [('shot_video', f'场{number} · ' + str(by_id.get(scene_id, {}).get('data', {}).get('label') or '分镜'), scene_id, number) for number, scene_id in sorted(scene_keys)]
    owned = lambda node: node.get('data', {}).get('sourceScriptId') == script_id
    base_x = float(script.get('position', {}).get('x', 0)) + _dimension(script, 'width', 360) + 120
    base_y = float(script.get('position', {}).get('y', 0)) + offset
    ancestor, visited = script, {script_id}
    while ancestor.get('parentId') in by_id and ancestor['parentId'] not in visited:
        ancestor = by_id[ancestor['parentId']]
        visited.add(ancestor['id'])
        base_x += float(ancestor.get('position', {}).get('x', 0))
        base_y += float(ancestor.get('position', {}).get('y', 0))
    groups = []
    next_x = base_x
    if shots_only:
        next_x = max([base_x] + [float(node.get('position', {}).get('x', 0)) + _dimension(node, 'width', 360) + 160 for node in nodes if node.get('type') == 'group' and owned(node) and node['data'].get('storyKind') in {'character_group', 'scene_group'}])
    for kind, prefix, scene_id, scene_number in categories:
        media = [node for node in nodes if owned(node) and node['data'].get('storyKind') == kind and _episode(node, script, by_id)[0] == episode and (kind != 'shot_video' or str(node['data'].get('sceneNodeId') or '') == scene_id and node['data'].get('sceneNumber') == scene_number)]
        if not media:
            continue
        if kind == 'shot_video':
            media.sort(key=lambda node: int(node['data'].get('shotIndex') or 0))
        members = []
        for shot_number, item in enumerate(media, 1):
            data = item['data']
            prompt_id = data.get('promptNodeId') or _id(script_id, kind + '_prompt', item['id'])
            prompt = by_id.get(prompt_id)
            if prompt is not None and (prompt.get('type') != 'text' or not owned(prompt)):
                raise ValueError('写作节点不属于当前剧本，请重新关联提示词')
            if prompt is None and kind != 'shot_video':
                prompt = {'id': prompt_id, 'type': 'text', 'position': {'x': 0, 'y': 0},
                          'data': {'label': f'{"角色" if kind == "character" else "场景"} · {data.get("label", "参考")} · 写作',
                                   'text': '' if data.get('deferredPrompt') else str(data.get('prompt') or data.get('text') or ''), 'mediaType': 'text',
                                   **({'deferredPrompt': True, 'writingPrompt': writing_requirements(str(data.get('writingRequirements') or '')), 'writingType': '图片提示词', 'writingSkill': 'none'} if data.get('deferredPrompt') else {}),
                                   'sourceScriptId': script_id, 'storyKind': kind + '_prompt', 'outputNodeId': item['id'], **_episode(item, script, by_id)[2]}}
                nodes.append(prompt)
                by_id[prompt_id] = prompt
            if prompt is None:
                continue
            if kind == 'shot_video':
                label = f'场{scene_number} · 镜头{shot_number}'
                data.update(label=label + ' · 视频', sceneShotIndex=shot_number)
                prompt['data'].update(label=label + ' · 写作', sceneShotIndex=shot_number)
            data['promptNodeId'] = prompt_id
            if (prompt_id, item['id']) not in pairs:
                edges.append({'id': f'{prompt_id}->{item["id"]}', 'source': prompt_id, 'target': item['id'], 'data': {'relation': 'prompt'}})
                pairs.add((prompt_id, item['id']))
            members.append((prompt, item))
        if not members:
            continue
        episode_label = _episode(media[0], script, by_id)[1]
        metadata = _episode(media[0], script, by_id)[2]
        group_id = _id(script_id, 'group', kind + (':' + episode if episode else '') + (':' + scene_id if scene_id else '') + (f':scene-{scene_number}' if scene_number else ''))
        group = by_id.get(group_id) or next((node for node in nodes if node.get('type') == 'group' and owned(node) and node['data'].get('storyKind') == kind + '_group' and str(node['data'].get('sceneNodeId') or '') == scene_id and (not scene_number or node['data'].get('sceneNumber', scene_number) == scene_number) and _episode(node, script, by_id)[0] == episode), None)
        if group:
            group_id = group['id']
        if group and (group.get('type') != 'group' or not owned(group)):
            raise ValueError('故事分组 ID 冲突')
        positions = {}
        x, group_height = 32, 240
        for start in range(0, len(members), 8):
            lane = members[start:start + 8]
            for prompt, item in lane:
                prompt.setdefault('style', {}).setdefault('width', 360)
                prompt['style'].setdefault('height', 260)
                item.setdefault('style', {}).setdefault('width', 360 if kind == 'shot_video' else 240)
                item['style'].setdefault('height', 240 if kind == 'shot_video' else 380)
            left = max(_dimension(prompt, 'width', 360) for prompt, _ in lane)
            right = max(_dimension(item, 'width', 360) for _, item in lane)
            y = 72
            for prompt, item in lane:
                positions[prompt['id']] = {'x': x, 'y': y}
                positions[item['id']] = {'x': x + left + 96, 'y': y}
                y += max(_dimension(prompt, 'height', 260), _dimension(item, 'height', 380)) + 72
            group_height = max(group_height, y - 40)
            x += left + right + 208
        group_width = x - 80
        if not group:
            location = {'x': next_x, 'y': base_y}
            # Reserve whole rectangles, including tall pre-existing groups.
            def overlaps(other):
                if owned(other) or other.get('parentId'):
                    return False
                x, y = float(other.get('position', {}).get('x', 0)), float(other.get('position', {}).get('y', 0))
                width = _dimension(other, 'width', 360)
                height = _dimension(other, 'height', 300)
                return location['x'] < x + width + 32 and location['x'] + group_width + 32 > x and location['y'] < y + height + 32 and location['y'] + group_height + 32 > y
            while any(overlaps(other) for other in nodes):
                location['y'] += 500
            group = {'id': group_id, 'type': 'group', 'position': location, 'data': {'label': ' · '.join(filter(None, [episode_label, prefix, title])), 'sourceScriptId': script_id, 'storyKind': kind + '_group', **({'sceneNodeId': scene_id} if scene_id else {}), **metadata}}
            nodes.append(group)
            by_id[group_id] = group
        if kind == 'shot_video':
            group['data'].update(label=' · '.join(filter(None, [episode_label, prefix, title])), sceneNumber=scene_number)
        group['data']['children'] = [node['id'] for pair in members for node in pair]
        group['style'] = {**group.get('style', {}), 'width': group_width, 'height': group_height}
        group.update(width=group_width, height=group_height)
        for prompt, item in members:
            for node in (prompt, item):
                node.update(parentId=group_id, extent='parent', position=positions[node['id']])
        next_x = max(next_x, group['position']['x'] + group_width + 160)
        groups.append(group)
    # React Flow requires parents to precede their children.
    result['nodes'] = [*groups, *(node for node in nodes if node not in groups)]
    return result
