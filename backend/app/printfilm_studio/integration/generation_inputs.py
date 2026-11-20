"""Resolve Agent node references to the same validated files used by UI generation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse, unquote
import re

from sqlalchemy import select, or_
from app.models_drama import DramaAsset
from app.printfilm_studio.integration.agent_media import read_asset_file
from app.services.studio_references import validate_upload, reference_params
from app.services.studio_tools import save_upload


def story_asset_prompt(document, source):
    data = source.get('data', {}) if source else {}
    if data.get('storyKind') not in {'character', 'scene'} or not data.get('promptNodeId'):
        return None
    writer = next((node for node in document['nodes'] if node['id'] == data['promptNodeId']), None)
    if not writer or writer.get('type') not in {'text', 'script'} or not any(edge['source'] == writer['id'] and edge['target'] == source['id'] for edge in document['edges']):
        raise ValueError('请连接该参考图的写作文本节点')
    if writer.get('data', {}).get('sourceScriptId') != data.get('sourceScriptId'):
        raise ValueError('写作文本必须属于同一剧本')
    prompt = str(writer.get('data', {}).get('text') or '').strip()
    if not prompt:
        raise ValueError('请先填写参考图的写作文本')
    return prompt


def story_video_inputs(document, source):
    if not source or source.get('data', {}).get('storyKind') != 'shot_video':
        return None
    data = source['data']
    by_id = {node['id']: node for node in document['nodes']}
    incoming = {edge['source'] for edge in document['edges'] if edge['target'] == source['id']}
    prompt_id = data.get('promptNodeId')
    text_node = by_id.get(prompt_id)
    if not text_node or prompt_id not in incoming or text_node.get('type') not in {'text', 'script'}:
        raise ValueError('请连接该分镜的提示词文本节点')
    script_id = data.get('sourceScriptId')
    if not script_id or text_node.get('data', {}).get('sourceScriptId') != script_id:
        raise ValueError('分镜提示词必须属于同一个剧本')
    prompt = str(text_node.get('data', {}).get('text') or '').strip()
    if not prompt:
        raise ValueError('分镜提示词为空，请先完善文本节点')
    ids = data.get('referenceNodeIds')
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
        raise ValueError('请关联该分镜的角色和场景参考图')
    references = []
    for ref_id in dict.fromkeys(ids):
        node = by_id.get(ref_id)
        if not node or ref_id not in incoming:
            raise ValueError('分镜参考图连线不完整，请先修复连线')
        ref = node.get('data', {})
        if ref.get('sourceScriptId') != script_id or ref.get('storyKind') not in {'character', 'scene'}:
            raise ValueError('分镜参考图必须来自同一剧本的角色或场景')
        label = str(ref.get('label') or '参考图')
        if ref.get('mediaType') not in {None, '', 'image'}:
            raise ValueError(f'{label} 不是图片参考')
        if ref.get('status') in {'queued', 'running', 'awaiting_composite', 'failed', 'error', 'cancelled'}:
            raise ValueError(f'请先完成参考图「{label}」的生成')
        urls = [url for url in ref.get('mediaUrls', []) if isinstance(url, str) and url.strip()] if isinstance(ref.get('mediaUrls'), list) else []
        try:
            index = max(0, min(int(float(ref.get('mediaIndex') or 0)), len(urls) - 1))
        except (TypeError, ValueError, OverflowError):
            index = 0
        url = urls[index] if urls else str(ref.get('mediaUrl') or ref.get('url') or ref.get('cover') or '')
        if not url:
            raise ValueError(f'请先生成参考图「{label}」')
        references.append({'node': node, 'url': url})
    if not any(ref['node']['data'].get('storyKind') == 'scene' for ref in references):
        raise ValueError('该分镜缺少场景参考图，请先关联场景')
    def resolve_mention(match):
        index = next((i for i, ref in enumerate(references) if match[2] == 'node' and ref['node']['id'] == unquote(match[3])), None)
        return f'@图片{index + 1}' if index is not None else unquote(match[1])
    provider_prompt = re.sub(r'@\[([^\]]*)\]\((node|asset):([^)]*)\)', resolve_mention, prompt)
    provider_prompt += '\n参考素材对应（按实际上传顺序）：\n' + '\n'.join(
        f'@图片{i+1}：{ref["node"]["data"].get("label") or "参考图"}，' +
        ('用于场景空间与光线' if ref['node']['data'].get('storyKind') == 'scene' else '仅用于人物身份和造型，不照搬背景或姿势') + '。'
        for i, ref in enumerate(references))
    return {'prompt': prompt, 'provider_prompt': provider_prompt, 'references': references}


def video_character_nodes(document, source):
    if not source:
        return []
    data = source['data']
    incoming = {edge['source'] for edge in document['edges'] if edge['target'] == source['id']}
    if data.get('storyKind') == 'shot_video':
        by_id = {node['id']: node for node in document['nodes']}
        ids = data.get('referenceNodeIds')
        return [by_id[ref] for ref in ids if isinstance(ref, str) and ref in incoming and ref in by_id] if isinstance(ids, list) else []
    return [source, *(node for node in document['nodes'] if node['id'] in incoming)]


def character_voice_references(nodes):
    references = {}
    for node in nodes:
        data = node['data']
        asset_id = data.get('voiceReferenceAssetId')
        if (node.get('type') == 'character' or data.get('storyKind') == 'character') and type(asset_id) is int and asset_id > 0:
            label = str(data.get('label') or '角色')
            labels = references.setdefault(asset_id, [])
            if label not in labels:
                labels.append(label)
    return references


def fixed_video_frame_nodes(document, source):
    if not source or source['data'].get('videoMode') != 'first_last_frame':
        return []
    ids = source['data'].get('videoFrameNodeIds')
    connected = {edge['source'] for edge in document['edges'] if edge['target'] == source['id']}
    by_id = {node['id']: node for node in document['nodes'] if node['id'] in connected}
    if (not isinstance(ids, list) or len(ids) != 2 or not all(isinstance(value, str) and value in by_id for value in ids)
            or ids[0] == ids[1]):
        raise ValueError('请在画布分别确认首帧和尾帧图片')
    return [by_id[value] for value in ids]


async def prepare_inputs(canvas, kind, document, source, asset_ids, *, generate_audio=None, model_id=None):
    ids = list(asset_ids or [])
    if any(type(value) is not int for value in ids):
        raise ValueError('reference_asset_ids 必须为素材 ID 数组')
    story = story_video_inputs(document, source) if kind == 'video' else None
    fixed_frames = fixed_video_frame_nodes(document, source) if kind == 'video' and not story else []
    if story:
        urls = [ref['url'] for ref in story['references']]
        linked_ids = [ref['node'].get('data', {}).get('assetId') for ref in story['references']]
        linked_ids = [value for value in linked_ids if type(value) is int]
        linked = (await canvas.db.scalars(select(DramaAsset).where(DramaAsset.project_id == canvas.project.id, or_(DramaAsset.url.in_(urls), DramaAsset.id.in_(linked_ids))))).all()
        resolved = []
        for ref in story['references']:
            asset = next((item for item in linked if item.url == ref['url']), None)
            if not asset:
                asset = next((item for item in linked if item.id == ref['node'].get('data', {}).get('assetId') and ref['url'] in {item.url, item.cover}), None)
            if not asset or asset.asset_type in {'audio', 'video'}:
                raise ValueError('分镜参考图片尚未绑定当前项目素材，请先保存参考图')
            # Different reference nodes can use the same asset. Preserve upload
            # positions so @图片N still addresses the corresponding node.
            resolved.append(asset.id)
        if ids and not set(ids).issubset(resolved):
            raise ValueError('生成引用必须与分镜角色和场景连线一致')
        ids = resolved
    elif fixed_frames:
        frame_asset_ids = [node['data'].get('assetId') for node in fixed_frames]
        if any(type(value) is not int or value <= 0 for value in frame_asset_ids):
            raise ValueError('请先完成首帧和尾帧图片生成并保存到当前项目')
        if ids and not set(ids).issubset(frame_asset_ids):
            raise ValueError('生成引用必须与已确认的首帧和尾帧一致')
        ids = frame_asset_ids
    elif source:
        connected = {edge['source'] for edge in document['edges'] if edge['target'] == source['id']}
        nodes = [source, *[node for node in document['nodes'] if node['id'] in connected]]
        for node in nodes:
            data = node.get('data', {})
            if data.get('assetId') and data['assetId'] not in ids:
                ids.append(data['assetId'])
            elif (data.get('mediaUrl') or data.get('url')) and not data.get('assetId'):
                raise ValueError('参考节点未绑定项目素材，请先将媒体添加到项目素材库')
    source_mode = source['data'].get('videoMode') if source else None
    voices = character_voice_references(video_character_nodes(document, source)) if kind == 'video' and not fixed_frames and source_mode != 'image_to_video' and generate_audio is not False else {}
    ids.extend(asset_id for asset_id in voices if asset_id not in ids)
    if not ids: return [], {}
    if kind == 'audio':
        raise ValueError('语音生成仅接收文本')
    limit = 12
    if kind == 'video':
        from app.config import get_settings
        from app.services.media_models.prices import resolve_strategy
        limit = resolve_strategy(model_id or get_settings().model_video).studio_reference_limit
    if len(ids) > limit:
        raise ValueError(f'当前模型最多支持 {limit} 项参考素材')
    assets = (await canvas.db.scalars(select(DramaAsset).where(DramaAsset.project_id == canvas.project.id, DramaAsset.id.in_(ids)))).all()
    by_id = {asset.id: asset for asset in assets}
    if any(asset_id not in by_id or by_id[asset_id].asset_type != 'audio' or not by_id[asset_id].url for asset_id in voices):
        raise ValueError('角色参考音频已不可用，请重新绑定当前项目的音频')
    if set(ids) != set(by_id): raise ValueError('参考素材不属于当前项目')
    kinds = [by_id[value].asset_type if by_id[value].asset_type in {'audio', 'video'} else 'image' for value in ids]
    if fixed_frames and kinds != ['image', 'image']:
        raise ValueError('首帧和尾帧必须是图片')
    if kind == 'image' and any(value != 'image' for value in kinds):
        raise ValueError('图片生成只支持图片参考')
    async def stopped(): return bool(getattr(canvas, 'stopped', lambda: False)())
    saved = []
    try:
        with TemporaryDirectory(prefix='printfilm-reference-') as temp:
            for index, asset_id in enumerate(ids):
                asset = by_id[asset_id]
                suffix = Path(urlparse(asset.url or '').path).suffix.lower()
                path = Path(temp) / f'input-{index}{suffix}'
                await read_asset_file(asset, path, stopped)
                raw = path.read_bytes()
                validate_upload(raw, path.name, kinds[index], None)
                saved.append(save_upload(canvas.user.id, raw, path.name))
        params = {}
        if kind == 'video':
            frames = not story and len(kinds) <= 2 and all(value == 'image' for value in kinds)
            refs = [{'file_index': index, 'role': ('first_frame' if index == 0 else 'last_frame') if frames else f'reference_{value}'} for index, value in enumerate(kinds)]
            params = {'video_mode': 'first_last_frame' if frames else 'omni_reference', 'references': refs, **await reference_params(canvas.db, canvas.user, refs, files=saved)}
            if voices:
                audio_ids = [asset_id for asset_id, media_kind in zip(ids, kinds) if media_kind == 'audio']
                params['_character_voice_directions'] = [
                    f'@音频{audio_ids.index(asset_id) + 1}：仅用于{"、".join(labels)}的对白音色，台词以本镜指定文本为准。'
                    for asset_id, labels in voices.items()
                ]
        return saved, params
    except BaseException:
        for path in saved: path.unlink(missing_ok=True)
        raise
