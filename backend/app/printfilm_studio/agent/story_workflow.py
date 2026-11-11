"""Apply one reviewed story-planning stage atomically, without generating media."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5
from .story_parameters import shot_parameters, reference_writing_prompt

from app.printfilm_studio.agent.tools import apply_canvas_patch, MAX_CANVAS_OPERATIONS


def _required(value, name, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name}必须为非空文本，最多 {limit} 字')
    return value.strip()


def _id(script_id, kind, identity):
    return f'story-{uuid5(NAMESPACE_URL, f"{script_id}:{kind}:{identity}").hex[:24]}'


def writing_requirements(requirements, video=False):
    if not video:
        from app.printfilm_studio.image_prompt_policy import image_writing_requirements
        requirements = image_writing_requirements(requirements)
    target = '视频' if video else '图片'
    return (f'根据下游{target}模型、已连接的参考素材和以下创作要求，生成最终可执行的中文{target}提示词。'
            '只输出提示词正文，不解释，不调用工具。保持参考人物身份、服装与场景一致，不臆造参考素材中没有的角色。'
            + ('明确景别、机位、动作、运镜、光线、时长及环境声；不添加未要求的旁白、字幕或文字。' if video else '明确主体、构图、时代、服装、环境及光线；统一采用动漫风格，正文明确写出动漫风格，不采用真人摄影或照片级写实。')
            + '\n\n创作要求：\n' + requirements)


def build_story_plan(document, name, payload):
    document = deepcopy(document)
    version = 1
    script_id = _required(payload.get('script_node_id'), '剧本节点 ID', 200)
    script = next((node for node in document['nodes'] if node['id'] == script_id), None)
    if not script or script.get('type') not in {'script', 'text'} or not str(script.get('data', {}).get('text') or '').strip():
        raise ValueError('请选择有正文的剧本节点')
    data = script.get('data') or {}
    is_assets = name == 'plan_story_assets'
    if not is_assets and not any(node.get('data', {}).get('sourceScriptId') == script_id and node.get('data', {}).get('storyKind') == 'scene' for node in document['nodes']):
        raise ValueError('请先补齐场景图片节点，再拆分分镜')
    items = payload.get('assets' if is_assets else 'shots')
    if not isinstance(items, list) or not items or len(items) > 100:
        raise ValueError('每次规划需要 1 至 100 个条目')
    from app.printfilm_studio.agent.story_graph import scene_sections, clean_name
    if is_assets:
        items = deepcopy(items)
        supplied = {clean_name(item.get('name', '')) for item in items if isinstance(item, dict) and item.get('kind') == 'scene'}
        for scene in scene_sections(str(data.get('text') or '')):
            if clean_name(scene['name']) not in supplied:
                items.append({'kind': 'scene', **scene})
                supplied.add(clean_name(scene['name']))
    existing = {node['id']: node for node in document['nodes']}
    single_script = sum(node.get('type') == 'script' for node in document['nodes']) == 1
    linked_assets = {edge['target'] for edge in document['edges'] if edge['source'] == script_id}
    operations, planned, seen = [], [], set()
    edge_pairs = {(edge['source'], edge['target']) for edge in document['edges']}
    def world_position(node):
        position = dict(node.get('position') or {'x': 0, 'y': 0})
        seen_parents = set()
        parent = node.get('parentId')
        while parent in existing and parent not in seen_parents:
            seen_parents.add(parent)
            container = existing[parent]
            position['x'] += float(container.get('position', {}).get('x', 0))
            position['y'] += float(container.get('position', {}).get('y', 0))
            parent = container.get('parentId')
        return position
    position = world_position(script)
    occupied = [world_position(node) for node in document['nodes'] if node.get('type') != 'group']
    scene_counts, scene_numbers = {}, {}
    existing_shots = [node for node in document['nodes'] if node.get('data', {}).get('sourceScriptId') == script_id and node['data'].get('storyKind') == 'shot_prompt']
    for shot in sorted(existing_shots, key=lambda node: int(node['data'].get('shotIndex') or 0)):
        details = shot['data']
        episode = details.get('episodeNumber') or details.get('episodeId')
        scenes = scene_numbers.setdefault(episode, {})
        scene_id = details.get('sceneNodeId')
        if scene_id:
            scenes[scene_id] = details.get('sceneNumber') or scenes.get(scene_id) or max(scenes.values(), default=0) + 1
    if not is_assets and all(isinstance(item, dict) and type(item.get("index")) is int for item in items):
        items = sorted(items, key=lambda item: item["index"])
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('规划条目必须为对象')
        label = _required(item.get('name'), '名称', 120)
        prompt = _required(item.get('prompt'), '图片提示词')
        if is_assets:
            from app.printfilm_studio.image_prompt_policy import image_writing_requirements
            prompt = _required(image_writing_requirements(prompt), '图片视觉要求')
        if is_assets:
            kind = item.get('kind')
            if kind not in {'character', 'scene'}:
                raise ValueError('素材类型必须为 character 或 scene')
            identity = label
            sources = []
            extra = {}
        else:
            kind = 'shot_prompt'
            order = item.get('index')
            if type(order) is not int or not 1 <= order <= 999:
                raise ValueError('分镜序号必须为 1 至 999 的整数')
            episode_identity = item.get('episodeNumber', data.get('episodeNumber')) or item.get('episodeId', data.get('episodeId'))
            identity = f'episode-{episode_identity}:{order}' if episode_identity else str(order)
            from app.printfilm_studio.agent.story_references import shot_references
            ids = shot_references(item, existing, script_id)
            previous_shot = existing.get(_id(script_id, 'shot_prompt', identity))
            if previous_shot and previous_shot['data'].get('referenceNodeIds'):
                ids = shot_references({'reference_node_ids': previous_shot['data']['referenceNodeIds']}, existing, script_id)
            parameters = shot_parameters(item, data)
            scene_id = next(ref for ref in ids if existing[ref].get('data', {}).get('storyKind') == 'scene' or existing[ref].get('type') == 'scene')
            scene_number = (previous_shot or {}).get('data', {}).get('sceneNumber') or item.get('scene_number')
            if scene_number is not None and (type(scene_number) is not int or not 1 <= scene_number <= 999):
                raise ValueError('场次序号必须为 1 至 999 的整数')
            episode_scenes = scene_numbers.setdefault(episode_identity, {})
            scene_number = scene_number or episode_scenes.get(scene_id) or max(episode_scenes.values(), default=0) + 1
            episode_scenes[scene_id] = scene_number
            scene_key = (episode_identity, scene_number, scene_id)
            earlier = sum(1 for shot in existing_shots if (shot['data'].get('episodeNumber') or shot['data'].get('episodeId')) == episode_identity and shot['data'].get('sceneNodeId') == scene_id and (shot['data'].get('sceneNumber') or scene_number) == scene_number and int(shot['data'].get('shotIndex') or 0) < order)
            scene_counts[scene_key] = max(scene_counts.get(scene_key, 0), earlier) + 1
            scene_index = scene_counts[scene_key]
            label = f'镜头{scene_index}'
            sources = []
            extra = {'sceneNumber': scene_number, 'sceneNodeId': scene_id, 'sceneShotIndex': scene_index, 'shotIndex': order, 'referenceNodeIds': list(dict.fromkeys(ids)), 'shotDescription': _required(item.get('description'), '分镜描述')}
        node_id = _id(script_id, kind, identity)
        if node_id in seen:
            raise ValueError('规划中有重复的角色、场景或分镜序号')
        seen.add(node_id)
        previous = existing.get(node_id)
        if is_assets and not previous:
            previous = next((node for node in existing.values() if node.get('type') == kind and (node.get('data', {}).get('sourceScriptId') == script_id or node.get('data', {}).get('sourceScriptId') is None and (single_script or node['id'] in linked_assets)) and clean_name(node.get('data', {}).get('label', '')) == clean_name(label)), None)
            if previous:
                node_id = previous['id']
                previous['data'] = {**previous.get('data', {}), 'sourceScriptId': script_id, 'storyKind': kind}
                operations.append({'op': 'update_node', 'node_id': node_id, 'changes': {'data': previous['data']}})
        # Repeating a stage must not overwrite existing prompts or finished media.
        if previous:
            if previous.get('data', {}).get('sourceScriptId') != script_id or previous.get('data', {}).get('storyKind') != kind:
                raise ValueError('规划节点 ID 冲突，请重试')
        else:
            for slot in range(len(occupied) + 1):
                location = {'x': float(position.get('x', 0)) + (420 if is_assets else 1260) + (slot % 2) * 380,
                            'y': float(position.get('y', 0)) + (slot // 2) * 340}
                if not any(abs(float(point.get('x', 0)) - location['x']) < 340 and abs(float(point.get('y', 0)) - location['y']) < 300 for point in occupied):
                    break
            occupied.append(location)
            node = {'id': node_id, 'type': kind if is_assets else 'text',
                    'position': location,
                    'data': {'label': label if is_assets else label + ' · 写作', 'prompt': '', 'text': str(item.get('description') or '') if is_assets else '',
                             'deferredPrompt': True, 'writingRequirements': prompt,
                             **({} if is_assets else {'writingPrompt': reference_writing_prompt(prompt, ids, existing, parameters, extra['shotDescription']), 'writingType': '镜头提示词', 'writingSkill': 'none', 'outputNodeId': _id(script_id, 'shot_video', identity)}),
                             'mediaType': 'image' if is_assets else 'text', 'sourceScriptId': script_id, 'storyKind': kind,
                             **{key: item.get(key, data.get(key)) for key in ('episodeId', 'episodeNumber', 'episodeTitle') if item.get(key, data.get(key)) is not None}, **extra}}
            operations.append({'op': 'add_node', 'node': node})
        for source in sources:
            if (source, node_id) not in edge_pairs:
                operations.append({'op': 'connect_canvas_nodes', 'edge': {'id': f'{source}->{node_id}', 'source': source, 'target': node_id}})
                edge_pairs.add((source, node_id))
        if not is_assets:
            video_id = _id(script_id, 'shot_video', identity)
            video = existing.get(video_id)
            if not video:
                prompt_position = world_position(previous or node)
                video = {'id': video_id, 'type': 'videoGeneration', 'position': {'x': prompt_position['x'] + 360, 'y': prompt_position['y']},
                         'data': {'label': label + ' · 视频', 'mediaType': 'video', 'sourceScriptId': script_id, 'storyKind': 'shot_video',
                                  'sceneNumber': scene_number, 'sceneNodeId': scene_id, 'sceneShotIndex': scene_index, 'shotIndex': order, 'promptNodeId': node_id, 'referenceNodeIds': list(dict.fromkeys(ids)), 'videoMode': 'omni_reference', 'prompt': '', **parameters}}
                video['data'].update({key: (previous or node)['data'][key] for key in ('episodeId', 'episodeNumber', 'episodeTitle') if key in (previous or node)['data']})
                operations.append({'op': 'add_node', 'node': video})
                occupied.append(video['position'])
            for source in [node_id, *ids]:
                if (source, video_id) not in edge_pairs:
                    operations.append({'op': 'connect_canvas_nodes', 'edge': {'id': f'{source}->{video_id}', 'source': source, 'target': video_id}})
                    edge_pairs.add((source, video_id))
            # A shot writer needs the actual reference results before writing its prompt.
            for source in ids:
                if (source, node_id) not in edge_pairs:
                    operations.append({'op': 'connect_canvas_nodes', 'edge': {'id': f'{source}->{node_id}', 'source': source, 'target': node_id}})
                    edge_pairs.add((source, node_id))
        planned.append({'id': node_id, 'label': previous.get('data', {}).get('label', label) if previous else label, 'kind': kind})
    flag = 'storyAssetsReady' if is_assets else 'storyShotsReady'
    manifest = {'storyCharacterNames': list(dict.fromkeys(clean_name(item['name']) for item in items if item['kind'] == 'character')),
                'storySceneNames': list(dict.fromkeys(clean_name(item['name']) for item in items if item['kind'] == 'scene'))} if is_assets else {}
    operations.append({'op': 'update_node', 'node_id': script_id, 'changes': {'data': {**data, **manifest, flag: True}}})
    candidate = deepcopy(document)
    # Validate all chunks against a private copy, then save once.
    for offset in range(0, len(operations), MAX_CANVAS_OPERATIONS):
        candidate = apply_canvas_patch(candidate, version, version, operations[offset:offset + MAX_CANVAS_OPERATIONS])
    candidate['edges'] = [edge for edge in candidate['edges'] if script_id not in (edge['source'], edge['target'])]
    from app.printfilm_studio.agent.story_layout import group_story_nodes
    candidate = group_story_nodes(candidate, script_id, shots_only=not is_assets)
    return candidate, {'ok': True, 'nodes': planned,
            'next_step': '请用户确认角色和场景提示词，再点击拆分分镜。' if is_assets else '请用户逐个选择分镜，确认模型与费用后生成视频。'}


async def apply_story_plan(name, payload, canvas):
    document, _ = await canvas.load()
    candidate, result = build_story_plan(document, name, payload)
    from .node_defaults import canvas_context
    selected = canvas_context(canvas).get('studio_director_selection', {})
    if selected:
        previous_ids = {node['id'] for node in document['nodes']}
        for node in candidate['nodes']:
            if node['id'] in previous_ids or node.get('type') != 'text':
                continue
            task = 'video_prompt' if node['data'].get('storyKind') == 'shot_prompt' else 'asset_plan'
            if task in selected:
                node['data']['writingDirectorSkillIds'] = selected[task]
    return {**result, 'version': await canvas.save(candidate)}
