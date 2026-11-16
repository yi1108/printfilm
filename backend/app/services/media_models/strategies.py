from __future__ import annotations

import re
from copy import copy
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any


class MediaValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"{field}: {message}")


IMAGE_RATIOS = ("auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9")
VIDEO_RATIOS = ("9:16", "16:9", "1:1")


def integer(value: Any, field: str, lo: int, hi: int) -> int:
    try:
        if isinstance(value, str) and len(value) > 64:
            raise ValueError
        number = Decimal(str(value))
        if isinstance(value, bool) or not number.is_finite() or number != number.to_integral_value():
            raise ValueError
    except (ValueError, InvalidOperation, TypeError):
        raise MediaValidationError(field, "必须是整数") from None
    # Compare Decimal bounds before allocating an integer (e.g. 1e999999999).
    if not lo <= number <= hi:
        raise MediaValidationError(field, f"必须在 {lo}–{hi} 之间")
    return int(number)


class MediaModelStrategy:
    model_id: str
    capability: str
    version = 1
    resolutions: tuple[str, ...]
    ratios: tuple[str, ...]
    max_reference_images = 9
    max_reference_audios = 0
    max_reference_videos = 0
    supports_generate_audio = False
    max_count = 1  # Existing gateway delivers one output per request.
    duration_min = 4
    duration_max = 15

    def with_reference_limits(self, limits: dict[str, int] | None):
        if limits is None:
            return self
        from app.schemas_routing import MediaReferenceLimits
        limits = MediaReferenceLimits.model_validate(limits).model_dump()
        configured = copy(self)
        configured.max_reference_images = limits["images"]
        configured.max_reference_videos = limits["videos"]
        configured.max_reference_audios = limits["audios"]
        return configured

    def validate_reference_counts(self, *, images: int = 0, videos: int = 0, audios: int = 0) -> None:
        for field, label, actual, maximum in (
            ("reference_images", "参考图片", images, self.max_reference_images),
            ("reference_videos", "参考视频", videos, self.max_reference_videos),
            ("reference_audios", "参考音频", audios, self.max_reference_audios),
        ):
            if actual > maximum:
                message = f"最多支持 {maximum} 个{label}" if maximum else f"不支持{label}"
                raise MediaValidationError(field, f"{self.model_id} {message}，当前 {actual} 个")

    def describe(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "strategy_id": self.model_id, "strategy_version": self.version,
            "capability": self.capability,
            "allowed_resolutions": list(self.resolutions),
            "allowed_aspect_ratios": list(self.ratios),
            "billing_unit": "image" if self.capability == "image" else "second",
            "max_count": self.max_count,
            "max_outputs_per_request": 1,
            "reference_limits": {"images": self.max_reference_images,
                                 "audios": self.max_reference_audios,
                                 "videos": self.max_reference_videos},
            "defaults": {"resolution": self.resolutions[min(1, len(self.resolutions) - 1)],
                         "aspect_ratio": "1:1" if self.capability == "image" else "9:16",
                         "count": 1},
        }
        if self.capability == "video":
            result.update(duration_min=self.duration_min, duration_max=self.duration_max,
                          duration_step=1, modes=["text_to_video", "image_to_video"])
            result["defaults"]["duration"] = 8
            result["supports_audio"] = self.supports_generate_audio
        else:
            result["modes"] = ["text_to_image", "image_to_image"]
        return result

    def normalize_and_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise MediaValidationError("params", "必须是对象")
        allowed = {"prompt", "negative", "negative_prompt", "resolution", "size", "aspect_ratio", "ratio",
                   "count", "reference_images", "reference_audios", "reference_videos", "style_ref_urls", "ref_urls", "image_url"}
        if self.capability == "video":
            allowed |= {"duration", "seconds", "generate_audio", "watermark", "return_last_frame",
                        "first_frame", "last_frame", "reference_audios", "reference_videos", "content"}
        for key in params:
            if key not in allowed:
                raise MediaValidationError(key, "该模型不支持此参数")
        for key in ("resolution", "size", "aspect_ratio", "ratio"):
            if key in params and params[key] is not None and not isinstance(params[key], str):
                raise MediaValidationError(key, "必须是字符串")
        out = {**self.describe()["defaults"], **params}
        res = str(params.get("resolution") or params.get("size") or out["resolution"]).strip()
        if self.capability == "image":
            res = self.image_resolution(res)
        else:
            res = res.lower()
        if res not in self.resolutions:
            raise MediaValidationError("resolution", f"支持 {', '.join(self.resolutions)}")
        out["resolution"] = res
        ratio = str(params.get("aspect_ratio") or params.get("ratio") or out["aspect_ratio"]).strip()
        if ratio not in self.ratios:
            raise MediaValidationError("aspect_ratio", f"支持 {', '.join(self.ratios)}")
        out["aspect_ratio"] = ratio
        out["count"] = integer(out["count"], "count", 1, self.max_count)
        for field in ("reference_images", "reference_audios", "reference_videos", "ref_urls"):
            values = params.get(field, [])
            if not isinstance(values, list):
                raise MediaValidationError(field, "参考素材必须是 URL 数组")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise MediaValidationError(field, "参考素材必须是非空 URL 字符串")
            out[field] = values
        out["reference_images"] = [*out["reference_images"], *out.pop("ref_urls")]
        if params.get("image_url"):
            if not isinstance(params["image_url"], str):
                raise MediaValidationError("image_url", "必须是 URL 字符串")
            out["reference_images"] = [*out["reference_images"], params["image_url"]]
            out.pop("image_url", None)
        styles = params.get("style_ref_urls") or []
        if not isinstance(styles, list) or any(not isinstance(value, str) or not value.strip() for value in styles):
            raise MediaValidationError("style_ref_urls", "必须是参考图 URL 数组")
        self.validate_reference_counts(images=len(out["reference_images"]) + len(styles),
                                       audios=len(out["reference_audios"]), videos=len(out["reference_videos"]))
        if self.capability == "video":
            out["duration"] = integer(params.get("duration", params.get("seconds", 8)),
                                      "duration", self.duration_min, self.duration_max)
            for flag in ("generate_audio", "watermark", "return_last_frame"):
                if flag in params and not isinstance(params[flag], bool):
                    raise MediaValidationError(flag, "必须是布尔值")
            if params.get("generate_audio") and not self.supports_generate_audio:
                raise MediaValidationError("generate_audio", "该模型暂不支持声音生成")
            for frame in ("first_frame", "last_frame"):
                if params.get(frame) and not isinstance(params[frame], str):
                    raise MediaValidationError(frame, "必须是参考图 URL 字符串")
            if params.get("first_frame") and out["reference_images"]:
                raise MediaValidationError("reference_images", "不能与 first_frame 同时使用")
            content = params.get("content") or []
            if not isinstance(content, list):
                raise MediaValidationError("content", "必须是数组")
            images = [x for x in content if isinstance(x, dict) and x.get("type") == "image_url"]
            audios = [x for x in content if isinstance(x, dict) and x.get("type") == "audio_url"]
            videos = [x for x in content if isinstance(x, dict) and x.get("type") == "video_url"]
            for role, label in (("first_frame", "首帧"), ("last_frame", "尾帧")):
                if sum(x.get("role") == role for x in images) + bool(params.get(role)) > 1:
                    raise MediaValidationError("references", f"{label}只能设置一张图片；多张参考图请使用全能参考模式")
            self.validate_reference_counts(
                images=len(images) + len(out["reference_images"]) + len(styles)
                       + bool(params.get("first_frame")) + bool(params.get("last_frame")),
                audios=len(audios) + len(out["reference_audios"]),
                videos=len(videos) + len(out["reference_videos"]),
            )
            roles = {x.get("role") for x in images}
            if params.get("first_frame"):
                roles.add("first_frame")
            if out["reference_images"] or styles:
                roles.add("reference_image")
            if "first_frame" in roles and "reference_image" in roles:
                raise MediaValidationError("reference_images", "首帧不能与多参考图同时使用")
        return out

    def image_resolution(self, size: str) -> str:
        if len(size) > 64:
            raise MediaValidationError("resolution", "图片分辨率格式过长")
        upper = size.upper()
        if upper in {"1K", "2K", "3K", "4K"}:
            return upper
        from app.services.drama.seedream_options import SEEDREAM_SIZE_MAP
        for tier, mapping in SEEDREAM_SIZE_MAP.items():
            if size.lower() in mapping.values():
                return tier
        match = re.fullmatch(r"(\d+)[xX×](\d+)", size)
        if match:
            area = int(match[1]) * int(match[2])
            if area <= 0 or area > 4096 * 4096:
                raise MediaValidationError("size", "不支持的像素尺寸")
            return "1K" if area <= 1_600_000 else "2K" if area <= 4_624_220 else "4K"
        raise MediaValidationError("resolution", "不支持的图片分辨率")

    def build_provider_request(self, params: dict[str, Any], route: Any) -> dict[str, Any]:
        p = self.normalize_and_validate(params)
        model = route.get("upstream_model") if isinstance(route, dict) else route.upstream_model
        if self.capability == "image":
            from app.services.drama.seedream_options import SEEDREAM_SIZE_MAP
            size = SEEDREAM_SIZE_MAP[p["resolution"]].get(p["aspect_ratio"], p["resolution"])
            return {"model": model, "prompt": p.get("prompt", ""), "size": size,
                    "resolution": p["resolution"], "aspect_ratio": p["aspect_ratio"],
                    "ref_urls": p["reference_images"], "style_ref_urls": p.get("style_ref_urls", [])}
        body = {key: p[key] for key in ("duration", "resolution", "generate_audio", "watermark", "return_last_frame") if key in p}
        content = list(p.get("content") or [])
        if p.get("prompt"):
            content.append({"type": "text", "text": p["prompt"]})
        for frame in ("first_frame", "last_frame"):
            if p.get(frame):
                content.append({"type": "image_url", "image_url": {"url": p[frame]}, "role": frame})
        for kind, field, role in (("image", "reference_images", "reference_image"),
                                  ("audio", "reference_audios", "reference_audio"),
                                  ("video", "reference_videos", "reference_video")):
            content.extend({"type": f"{kind}_url", f"{kind}_url": {"url": url}, "role": role} for url in p[field])
        content.extend({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"}
                       for url in p.get("style_ref_urls", []))
        body.update(model=model, ratio=p["aspect_ratio"], content=content)
        return body

    def quote(self, params: dict[str, Any], price_snapshot: dict[str, Any]) -> dict[str, Any]:
        p = self.normalize_and_validate(params)
        try:
            price = Decimal(str(price_snapshot[self.model_id][p["resolution"]]))
            if not price.is_finite() or price <= 0:
                raise ValueError
        except (KeyError, InvalidOperation, ValueError, TypeError):
            raise MediaValidationError("price", f"{self.model_id}/{p['resolution']} 尚未配置价格") from None
        multiplier = p["duration"] if self.capability == "video" else 1
        amount = int((price * multiplier * 100).to_integral_value(rounding=ROUND_CEILING))
        return {"model_id": self.model_id, "strategy_id": self.model_id, "strategy_version": self.version,
                "capability": self.capability, "resolution": p["resolution"],
                "duration": p.get("duration"), "count": p["count"],
                "unit_price_yuan": format(price, ".4f"), "unit_charge_fen": amount,
                "total_fen": amount * p["count"], "params": p}


class ImageModelStrategy(MediaModelStrategy):
    max_count = 100  # Batched delivery uses separate one-image gateway requests.
    capability = "image"
    resolutions = ("1K", "2K")
    ratios = IMAGE_RATIOS


class Seedream50ProStrategy(ImageModelStrategy):
    model_id = "seedream-5.0-pro"


class Seedream50Strategy(ImageModelStrategy):
    model_id = "seedream-5.0"


class Seedream50FlashStrategy(ImageModelStrategy):
    model_id = "seedream-5.0-flash"


class GptImage2Strategy(ImageModelStrategy):
    model_id = "gpt-image-2"


class GptImage25Strategy(ImageModelStrategy):
    model_id = "gpt-image-2.5"
    resolutions = ("1K", "2K", "4K")


class VideoModelStrategy(MediaModelStrategy):
    capability = "video"
    resolutions = ("480p", "720p")
    ratios = VIDEO_RATIOS
    max_reference_audios = 3
    max_reference_videos = 3
    supports_generate_audio = True


class Seedance25Strategy(VideoModelStrategy):
    model_id = "seedance-2.5"
    resolutions = ("480p", "720p", "1080p")
    duration_max = 30


class Seedance20Strategy(VideoModelStrategy):
    model_id = "seedance-2.0"


class Seedance20FastStrategy(VideoModelStrategy):
    model_id = "seedance-2.0-fast"


class MiniMaxH3Strategy(VideoModelStrategy):
    model_id = "MiniMax-H3"
    resolutions = ("480p", "768p")
    max_reference_audios = 0
    max_reference_videos = 0


_STRATEGIES = tuple(cls() for cls in (Seedream50ProStrategy, Seedream50Strategy, Seedream50FlashStrategy,
                                    GptImage2Strategy, GptImage25Strategy, Seedance25Strategy,
                                    Seedance20Strategy, Seedance20FastStrategy, MiniMaxH3Strategy))


def strategies() -> tuple[MediaModelStrategy, ...]:
    return _STRATEGIES


def get_strategy(model_id: str) -> MediaModelStrategy:
    from app.services.media_model_presets import resolve_preset_alias
    raw = resolve_preset_alias(model_id).lower()
    raw = {"doubao-seedance-2-0": "seedance-2.0", "doubao-seedance-2-5": "seedance-2.5",
           "ark-seedream": "seedream-5.0-pro", "kie-seedream-5": "seedream-5.0"}.get(raw, raw)
    for strategy in _STRATEGIES:
        if raw == strategy.model_id.lower():
            return strategy
    # Known dated Ark IDs; unknown families do not receive guessed capabilities.
    for prefix, canonical in (("doubao-seedance-2-5-", "seedance-2.5"),
                               ("doubao-seedance-2-0-fast-", "seedance-2.0-fast"),
                               ("doubao-seedance-2-0-", "seedance-2.0"),
                               ("doubao-seedream-5-0-pro-", "seedream-5.0-pro"),
                               ("doubao-seedream-5-0-", "seedream-5.0")):
        if raw.startswith(prefix) and raw[len(prefix):].isdigit():
            return get_strategy(canonical)
    raise MediaValidationError("model", f"未注册模型策略：{model_id}")
