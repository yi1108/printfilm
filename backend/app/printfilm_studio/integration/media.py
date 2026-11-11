"""Media integration seam; concrete task creation stays in existing services."""

from typing import Any


def media_task_payload(kind: str, prompt: str, **options: Any) -> dict[str, Any]:
    """Build a normalized payload for the existing task scheduler."""
    if kind not in {"image", "video", "audio"}:
        raise ValueError("unsupported media kind")
    # ``kind`` is already represented by the selected tool id and ToolRun.kind.
    # Keeping it out of the strategy params is required because media model
    # validation rejects unknown keys.
    return {"prompt": prompt.strip(), **options}


async def create_media_task(canvas, kind: str, prompt: str, **options: Any) -> dict[str, Any]:
    """Create a Printfilm Studio media task through the existing billing queue."""
    from app.services.studio_generation import enqueue_generation
    from app.models_tasks import TaskRun
    from uuid import uuid4

    tool_id = {"image": "t2i", "video": "t2v", "audio": "audio"}.get(kind)
    if not tool_id:
        raise ValueError("unsupported media kind")
    from app.printfilm_studio.agent.node_defaults import canvas_context
    preferred = (canvas_context(canvas).get('studio_node_defaults') or {}).get(kind)
    if preferred:
        options['model_id'] = preferred
    reuse_node = options.pop('_reuse_node', False)
    source_id = options.pop('node_id', None)
    document, _ = await canvas.load()
    source = next((node for node in document['nodes'] if node['id'] == source_id), None)
    if source_id and not source:
        raise ValueError('参考节点不存在')
    from app.printfilm_studio.integration.generation_inputs import prepare_inputs, story_video_inputs, story_asset_prompt
    story = story_video_inputs(document, source) if kind == 'video' else None
    story_asset = kind == 'image' and source and source.get('data', {}).get('sourceScriptId') and source.get('data', {}).get('storyKind') in {'character', 'scene'} and source.get('type') == source['data']['storyKind']
    story_output = bool(story or story_asset or reuse_node and source)
    if story_output:
        if source.get('data', {}).get('status') in {'queued', 'running', 'awaiting_composite'}:
            raise ValueError('该节点已有生成任务，请等待完成后重试')
        prompt = story['prompt'] if story else story_asset_prompt(document, source) or str(source['data'].get('prompt') or '').strip() or prompt
        if not prompt:
            raise ValueError('参考图片提示词为空，请先完善节点提示词')
        options['node_id'] = source['id']
    if kind == 'video' and source and source.get('type') in {'video', 'videoGeneration'}:
        # Agent calls and background workflows use the same concrete node settings.
        from app.printfilm_studio.writing_context import assert_video_binding
        for field, key in (('modelId', 'model_id'), ('ratio', 'ratio'), ('duration', 'duration'), ('resolution', 'resolution')):
            if source['data'].get(field):
                options[key] = source['data'][field]
        if 'generateAudio' in source['data']:
            options['generate_audio'] = source['data']['generateAudio']
        if options.get('ratio') == 'auto':
            options['ratio'] = '16:9'
        writer = next((n for n in document['nodes'] if n['id'] == source['data'].get('promptNodeId')), None)
        assert_video_binding(writer, source, options)
    files, reference_options = await prepare_inputs(canvas, kind, document, source, options.pop('reference_asset_ids', None))
    if kind == 'image' and files:
        tool_id = 'i2i'
    if 'count' in options:
        options['pack'] = str(options.pop('count'))
    options.update(reference_options)
    try:
        # Non-story writers also store stable canvas markers; upstream providers
        # must receive readable labels rather than internal IDs.
        from urllib.parse import unquote
        import re
        request_prompt = story['provider_prompt'] if story else re.sub(r'@\[([^\]]*)\]\((?:node|asset):[^)]*\)', lambda m: '@' + unquote(m[1]), prompt)
        if kind == 'video':
            from app.printfilm_studio.video_prompt_audio import video_prompt_audio
            request_prompt = video_prompt_audio(request_prompt, options.get('model_id'))
        result = await enqueue_generation(canvas.db, canvas.user, tool_id=tool_id, prompt=request_prompt,
            params=media_task_payload(kind, request_prompt, **options), files=files, drama_project_id=getattr(canvas.project, 'id', None))
    except BaseException:
        for path in files: path.unlink(missing_ok=True)
        raise
    # Task admission, node linkage and version update share one transaction.
    # A save conflict rolls the queued task back before the scheduler sees it.
    task = await canvas.db.get(TaskRun, result['platform_task_id'])
    task.cancelable = True
    if canvas.db.info.get('studio_agent_run_id'):
        task.payload = {**task.payload, 'studio_agent_run_id': canvas.db.info['studio_agent_run_id']}
    node_id = source['id'] if story_output else f'agent-{uuid4()}'
    if story_output:
        from datetime import datetime, UTC
        data = source['data']
        history = list(data.get('mediaHistory') or [])
        previous = data.get('mediaUrl') or data.get('url')
        if previous:
            history.append({key: data.get(key) for key in ('mediaUrl', 'mediaUrls', 'mediaIndex', 'assetId', 'mediaType', 'label', 'prompt', 'modelId', 'ratio', 'resolution', 'duration')})
            history[-1].update(data.get('mediaOutputMetadata') or {})
            history[-1].update(mediaUrl=previous, savedAt=datetime.now(UTC).isoformat())
        source['data'] = {**data, 'mediaOutputMetadata': {'prompt':prompt,'modelId':options.get('model_id'),'ratio':options.get('ratio'),'resolution':options.get('resolution'),'duration':options.get('duration')}, 'prompt': prompt, 'mediaType': kind, 'taskId': result['task_id'], 'status': 'queued',
                          'mediaUrl': None, 'url': None, 'mediaUrls': [], 'cover': None, 'assetId': None, 'mediaHistory': history[-30:],
                          'modelId': options.get('model_id'), 'resolution': options.get('resolution'), 'ratio': options.get('ratio'), **({'duration': options.get('duration')} if kind == 'video' else {}),
                          **({field: options[key] for field, key in (('modelId', 'model_id'), ('ratio', 'ratio'), ('duration', 'duration'), ('resolution', 'resolution')) if options.get(key) is not None}), **({'videoMode': 'omni_reference'} if story else {})}
    else:
        document['nodes'].append({'id': node_id, 'type': kind, 'position': {'x': (source or {}).get('position', {}).get('x', 0) + 320, 'y': (source or {}).get('position', {}).get('y', 100)}, 'data': {'label': prompt[:24], 'prompt': prompt, 'mediaType': kind, 'taskId': result['task_id'], 'status': 'queued', 'modelId': options.get('model_id'), **({'generateAudio': options['generate_audio']} if options.get('generate_audio') is not None else {})}})
    if source and not story_output:
        document['edges'].append({'id': f'edge-{uuid4()}', 'source': source_id, 'target': node_id})
    try:
        version = await canvas.save(document)
    except BaseException:
        await canvas.db.rollback()
        for path in files: path.unlink(missing_ok=True)
        raise
    return {**result, 'node_id': node_id, 'version': version}
