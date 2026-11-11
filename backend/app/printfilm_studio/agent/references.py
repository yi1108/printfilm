"""Small display snapshots taken from authorized references at send time."""
import math


def _text(*values, limit=8192):
    return next((value[:limit] for value in values if isinstance(value, str) and value.strip()), '')


def asset_reference(asset):
    asset_type = str(asset.asset_type or getattr(asset, 'type', '') or '').lower()
    kind = 'video' if asset_type == 'video' else 'audio' if asset_type in {'audio', 'voice'} else 'image'
    return dict(key=f'asset-{asset.id}', assetId=asset.id, label=_text(asset.name, limit=200) or f'素材 {asset.id}',
                kind=kind, thumbnail=_text(asset.cover, asset.url if kind == 'image' else ''),
                mediaUrl=_text(asset.url), text='')


def node_reference(node, assets):
    data = node.get('data') or {}
    node_type = str(node.get('type') or '').lower()
    kind = str(data.get('mediaType') or '').lower()
    if kind not in {'image', 'video', 'audio'}:
        if node_type in {'video', 'videogeneration', 'shot', 'frameanalysis', 'compose', 'motion', 'storyboard', 'interpolate', 'control_video', 'fill_frames', 'task'}:
            kind = 'video'
        elif node_type in {'audio', 'audiogeneration', 'voice'}:
            kind = 'audio'
        elif node_type in {'image', 'imagegeneration', 'scene', 'character', 'prop', 'material', 'asset', 'inpaint', 'outpaint', 'upscale'}:
            kind = 'image'
        else:
            kind = 'text'
    asset = next((item for item in assets if str(item.id) == str(data.get('assetId') or data.get('asset_id'))), None)
    variants = list(dict.fromkeys(item.strip() for item in (data.get('mediaUrls') or []) if isinstance(item, str) and item.strip())) if isinstance(data.get('mediaUrls'), list) else []
    try:
        index = float(data.get('mediaIndex') or 0)
        index = max(0, min(math.floor(index), len(variants) - 1)) if math.isfinite(index) else 0
    except (ValueError, TypeError):
        index = 0
    media = _text(variants[index] if variants else '', data.get('mediaUrl'), data.get('url'), data.get('cover'), getattr(asset, 'url', ''))
    cover = _text(data.get('cover'), data.get('thumbnail'), data.get('thumbnailUrl'), data.get('poster'), getattr(asset, 'cover', ''))
    return dict(key=f"node-{node['id']}", nodeId=node['id'], label=_text(data.get('label'), data.get('name'), limit=200) or '未命名节点',
                kind=kind, thumbnail=_text(media, cover) if kind == 'image' else cover, mediaUrl=media,
                text=_text(data.get('text'), data.get('prompt'), limit=180))
