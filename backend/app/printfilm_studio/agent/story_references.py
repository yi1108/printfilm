"""Resolve an omitted scene only when the current story gives an unambiguous match."""
import re


def shot_references(item, existing, script_id):
    ids = item.get('reference_node_ids', [])
    if not isinstance(ids, list) or len(ids) > 20 or not all(isinstance(value, str) for value in ids):
        raise ValueError('分镜参考节点列表无效')
    ids = list(dict.fromkeys(ids))
    refs = [node for node in existing.values() if node.get('data', {}).get('sourceScriptId') == script_id and node['data'].get('storyKind') in {'character', 'scene'}]
    valid = {node['id']: node for node in refs}
    if any(identity not in valid for identity in ids):
        raise ValueError('分镜只能引用当前剧本已抽取的角色与场景图片节点，请勿使用写作节点 ID')
    scenes = [node for node in refs if node['data']['storyKind'] == 'scene']
    scene_refs = [identity for identity in ids if valid[identity]['data']['storyKind'] == 'scene']
    if len(scene_refs) > 1:
        raise ValueError('一个镜头只能属于一个场景，请拆成不同场次分别规划')
    if scene_refs:
        if item.get('scene_node_id') and item['scene_node_id'] != scene_refs[0]:
            raise ValueError('scene_node_id 与引用的场景不一致')
        return ids
    explicit = item.get('scene_node_id')
    if explicit:
        if not isinstance(explicit, str) or explicit not in valid or valid[explicit]['data']['storyKind'] != 'scene':
            raise ValueError('scene_node_id 必须是当前剧本的场景图片节点 ID')
        return [*ids, explicit]
    normalize = lambda value: re.sub(r'[\s【】《》:：·—_-]', '', str(value or ''))
    place = normalize(item.get('scene_name') or item.get('location') or item.get('scene'))
    body = normalize(' '.join(str(item.get(key) or '') for key in ('name', 'description', 'prompt')))
    matches = [node for node in scenes if (label := normalize(node['data'].get('label'))) and (label == place or not place and label in body)]
    if len(matches) == 1:
        return [*ids, matches[0]['id']]
    if not place and len(scenes) == 1:
        return [*ids, scenes[0]['id']]
    choices = '；'.join(f'{node["data"].get("label", "场景")}={node["id"]}' for node in scenes)
    raise ValueError(f'分镜「{item.get("name", "未命名")}」尚未明确对应场景。请在 reference_node_ids 或 scene_node_id 中选取一个当前剧本场景：{choices}。画布未修改。')
