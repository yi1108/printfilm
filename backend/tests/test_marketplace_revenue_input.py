"""作者请求不能覆盖由运营管理的平台分成。"""
import pytest
from pydantic import ValidationError
from app.marketplace.schemas import WorkInput, WorkUpdate, SeriesInput, SeriesUpdate, EpisodeInput, EpisodeUpdate


@pytest.mark.parametrize("model,payload", [
    (WorkInput, {"title": "work", "price_fen": 0}),
    (WorkUpdate, {"title": "work", "price_fen": 0, "version": 1}),
    (SeriesInput, {"title": "series"}),
    (SeriesUpdate, {"title": "series", "version": 1}),
    (EpisodeInput, {"title": "episode", "episode_no": 1}),
    (EpisodeUpdate, {"title": "episode", "episode_no": 1, "version": 1}),
])
def test_author_inputs_reject_share_override(model, payload):
    assert "share_bps" not in model.model_validate(payload).model_dump()
    for value in (None, 0, 2000):
        with pytest.raises(ValidationError) as error:
            model.model_validate({**payload, "share_bps": value})
        assert any(item["loc"] == ("share_bps",) and item["type"] == "extra_forbidden"
                   for item in error.value.errors())
