import pytest
from app.printfilm_studio.recipes import normalize_recipe


def test_recipe_strips_project_specific_media_and_running_tasks():
    raw = {'secretRoot': 'drop', 'nodes': [{'id': 'a', 'type': 'image', 'data': {'prompt': 'portrait', 'assetId': 9, 'taskId': '3', 'mediaUrl': 'private', 'status': 'running', 'modelId': 'image-model'}}]}
    doc = normalize_recipe(raw)
    assert doc['nodes'][0]['data'] == {'prompt': 'portrait', 'modelId': 'image-model'}
    assert 'secretRoot' not in doc
    assert raw['nodes'][0]['data']['assetId'] == 9


def test_recipe_rejects_invalid_or_cyclic_group_references():
    for nodes in ([{'id': 'a', 'parentId': 'missing'}], [{'id': 'a', 'parentId': 'b'}, {'id': 'b', 'parentId': 'a'}]):
        with pytest.raises(ValueError):
            normalize_recipe({'nodes': nodes})


def test_recipe_preserves_prompt_connections_and_group_dimensions():
    doc = normalize_recipe({'nodes': [{'id': 'g', 'type': 'group', 'style': {'width': 600, 'height': 400}}, {'id': 'a', 'parentId': 'g', 'data': {'prompt': 'Hello'}}], 'edges': [{'id': 'e', 'source': 'g', 'target': 'a'}]})
    assert doc['nodes'][0]['style']['width'] == 600
    assert doc['nodes'][1]['parentId'] == 'g'
    assert doc['edges'][0]['target'] == 'a'
