"""Browser defaults apply to newly created Agent nodes, including reviewed proposals."""


def canvas_context(canvas):
    return getattr(canvas, 'context_info', None) or getattr(getattr(canvas, 'db', None), 'info', {})


def apply_node_defaults(document, existing_ids, context):
    defaults = context.get('studio_node_defaults') or {}
    for node in document.get('nodes', []):
        if node.get('id') in existing_ids:
            continue
        if node.get('data', {}).get('taskId') and node.get('data', {}).get('modelId'):
            continue  # An admitted task must keep the actual submitted model.
        kind = node.get('type', '')
        kind = node.get('data', {}).get('mediaType') or ('text' if kind in {'script', 'text', 'textGeneration'} else 'video' if kind in {'video', 'videoGeneration', 'shot'} else 'image' if kind in {'image', 'imageGeneration', 'scene', 'character', 'prop', 'material', 'asset'} else kind)
        if kind in {'image', 'video'}:
            node.setdefault('data', {}).setdefault('ratio', '2:3' if kind == 'image' else '16:9')
        model = defaults.get(kind)
        if model and kind in {'text', 'image', 'video'}:
            node.setdefault('data', {})['writingModel' if kind == 'text' else 'modelId'] = model
