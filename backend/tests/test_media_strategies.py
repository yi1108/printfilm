from decimal import Decimal

import pytest

from app.services.media_models import get_strategy, strategies


@pytest.mark.parametrize("model,resolutions,maximum", [
    ("seedream-5.0-pro", ["1K", "2K"], None),
    ("gpt-image-2.5", ["1K", "2K", "4K"], None),
    ("seedance-2.5", ["480p", "720p", "1080p"], 30),
    ("seedance-2.0", ["480p", "720p"], 15),
    ("MiniMax-H3", ["480p", "768p"], 15),
])
def test_model_contract(model, resolutions, maximum):
    description = get_strategy(model).describe()
    assert description["allowed_resolutions"] == resolutions
    assert description.get("duration_max") == maximum


def test_alias_and_registry():
    assert len(strategies()) == 9
    assert get_strategy("seedance-2-5").model_id == "seedance-2.5"
    assert get_strategy("doubao-seedance-2-0-260128").model_id == "seedance-2.0"
    with pytest.raises(ValueError, match="model"):
        get_strategy("not-registered")


@pytest.mark.parametrize("params,field", [
    ({"resolution": "1080p"}, "resolution"),
    ({"duration": 30}, "duration"),
    ({"duration": 4.5}, "duration"),
    ({"duration": True}, "duration"),
    ({"duration": "1e999999999"}, "duration"),
    ({"duration": "9" * 10000}, "duration"),
    ({"aspect_ratio": "21:9"}, "aspect_ratio"),
    ({"surprise": True}, "surprise"),
    ({"reference_images": ["https://a"] * 10}, "reference_images"),
])
def test_invalid_parameters_are_rejected_without_clamping(params, field):
    with pytest.raises(ValueError, match=field):
        get_strategy("seedance-2.0").normalize_and_validate(params)


def test_fixed_price_per_output_rounding():
    strategy = get_strategy("gpt-image-2.5")
    params = strategy.normalize_and_validate({"resolution": "4k", "count": 3})
    quote = strategy.quote(params, {"gpt-image-2.5": {"4K": "0.0125"}})
    assert quote["unit_charge_fen"] == 2
    assert quote["total_fen"] == 6
    assert quote["unit_price_yuan"] == "0.0125"


def test_video_quote_uses_submitted_duration():
    strategy = get_strategy("MiniMax-H3")
    params = strategy.normalize_and_validate({"resolution": "768p", "duration": 8})
    quote = strategy.quote(params, {"MiniMax-H3": {"768p": Decimal("0.1234")}})
    assert quote["unit_charge_fen"] == 99
    assert quote["duration"] == 8


def test_missing_price_is_not_token_fallback():
    strategy = get_strategy("seedream-5.0")
    with pytest.raises(ValueError, match="price"):
        strategy.quote(strategy.normalize_and_validate({}), {})


def test_image_pixel_mapping_and_upstream_request():
    strategy = get_strategy("seedream-5.0-pro")
    params = strategy.normalize_and_validate({"size": "1584x2816", "aspect_ratio": "9:16"})
    assert params["resolution"] == "2K"
    body = strategy.build_provider_request(params, {"upstream_model": "seedream-5-0-pro"})
    assert body["model"] == "seedream-5-0-pro"
    assert body["size"] == "1584x2816"
    with pytest.raises(ValueError, match="resolution"):
        strategy.normalize_and_validate({"resolution": "4K"})


def test_first_frame_and_reference_images_are_mutually_exclusive():
    with pytest.raises(ValueError, match="reference_images"):
        get_strategy("seedance-2.5").normalize_and_validate({
            "first_frame": "https://first", "reference_images": ["https://ref"],
        })


def test_quote_rejects_first_frame_supplied_in_two_fields():
    with pytest.raises(ValueError, match="首帧只能设置一张"):
        get_strategy("seedance-2.0").quote({
            "first_frame": "https://cdn.example.com/first.jpg",
            "content": [{"type": "image_url", "role": "first_frame", "image_url": {"url": "https://cdn.example.com/second.jpg"}}],
        }, {})
