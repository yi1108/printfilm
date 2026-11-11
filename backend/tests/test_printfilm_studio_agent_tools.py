import pytest

from app.printfilm_studio.agent.tools import apply_canvas_patch, tool_definitions


def test_canvas_patch_is_atomic_and_versioned():
    document = {"version": 1, "nodes": [{"id": "n1", "type": "text"}], "edges": []}
    updated = apply_canvas_patch(document, 4, 4, [{"op": "add_node", "node": {"id": "n2", "type": "image"}}, {"op": "connect_canvas_nodes", "edge": {"id": "e1", "source": "n1", "target": "n2"}}])
    assert len(updated["nodes"]) == 2
    with pytest.raises(ValueError, match="conflict"):
        apply_canvas_patch(document, 3, 4, [])
    with pytest.raises(ValueError):
        apply_canvas_patch(document, 4, 4, [{"op": "remove_node", "node_id": "missing"}])


def test_tool_registry_contains_declared_first_batch():
    names = {item["name"] for item in tool_definitions()}
    assert {"read_canvas", "create_image_task", "estimate_generation_price"} <= names
