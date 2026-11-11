from app.printfilm_studio.canvas.codec import decode_canvas_document, encode_canvas_document
import pytest


def test_codec_accepts_toonflow_compatibility_document_and_preserves_unknown_fields():
    raw = {
        "toonflowCanvas": True,
        "version": 1,
        "nodes": [{"id": "n1", "type": "text", "position": {"x": 1, "y": 2}, "data": {"label": "hello"}, "future": 9}],
        "edges": [],
        "viewport": {"x": 1, "y": 2, "zoom": 0.8},
        "custom": {"keep": True},
    }
    document = decode_canvas_document(raw)
    encoded = encode_canvas_document(document)
    assert encoded["toonflowCanvas"] is True
    assert encoded["custom"] == {"keep": True}
    assert encoded["nodes"][0]["future"] == 9


def test_codec_fills_missing_arrays_and_rejects_invalid_edges():
    document = decode_canvas_document({"version": 1})
    assert document["nodes"] == []
    assert document["edges"] == []
    try:
        decode_canvas_document({"version": 1, "edges": [{"id": "e", "source": "missing", "target": "n"}]})
    except ValueError as exc:
        assert "edge" in str(exc).lower()
    else:
        raise AssertionError("invalid edge should be rejected")


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_codec_rejects_non_finite_coordinates(value):
    with pytest.raises(ValueError, match='finite'):
        decode_canvas_document({'viewport': {'zoom': value}})


def test_codec_rejects_duplicate_edge_ids():
    with pytest.raises(ValueError, match='unique'):
        decode_canvas_document({'nodes': [{'id': 'a'}, {'id': 'b'}], 'edges': [{'id': 'e', 'source': 'a', 'target': 'b'}, {'id': 'e', 'source': 'b', 'target': 'a'}]})
