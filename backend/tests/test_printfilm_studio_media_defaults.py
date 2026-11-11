import pytest

from app.printfilm_studio.agent.node_defaults import apply_node_defaults
from app.printfilm_studio.workflow import params_for
from app.printfilm_studio.writing_context import output_settings


@pytest.mark.parametrize('kind,ratio', [('image', '2:3'), ('video', '16:9')])
@pytest.mark.parametrize('saved', [None, '', 'auto', '1:1'])
def test_writing_and_generation_resolve_the_same_ratio(kind, ratio, saved):
    node = {'id': 'out', 'type': kind + 'Generation', 'data': {'ratio': saved}}
    writer = {'id': 'writer', 'data': {'outputNodeId': 'out'}}
    document = {'nodes': [node], 'edges': []}
    expected = '1:1' if saved == '1:1' else ratio
    assert params_for(node, {})[1]['ratio'] == expected
    assert output_settings(writer, document, {})[0]['ratio'] == expected
    if saved in (None, ''):
        assert params_for(node, {kind + 'Ratio': '9:16'})[1]['ratio'] == '9:16'
        assert output_settings(writer, document, {kind + 'Ratio': '9:16'})[0]['ratio'] == '9:16'


def test_agent_defaults_only_fill_new_nodes_without_overriding_explicit_choices():
    nodes = [{'id': 'image', 'type': 'character', 'data': {}},
             {'id': 'video', 'type': 'videoGeneration', 'data': {}},
             {'id': 'explicit', 'type': 'scene', 'data': {'ratio': '1:1'}},
             {'id': 'old', 'type': 'videoGeneration', 'data': {}}]
    apply_node_defaults({'nodes': nodes}, {'old'}, {})
    assert [n['data'].get('ratio') for n in nodes] == ['2:3', '16:9', '1:1', None]
