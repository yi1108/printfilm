"""文字模型路由：渠道 models 变更后默认同步到通用 OpenAI 兼容模型。"""

from app.schemas_routing import DefaultModels, LogicalModel, LogicalModelBinding, SystemModelChannel
from app.services.model_routing_config import (
    normalize_default_models,
    synchronize_logical_models_with_channels,
)


def _channel(**kwargs) -> SystemModelChannel:
    return SystemModelChannel(
        id=kwargs.get("id", "openai-default"),
        name=kwargs.get("name", "OpenAI 兼容 LLM"),
        base_url=kwargs.get("base_url", "https://api.deepseek.com"),
        api_key=kwargs.get("api_key", "sk-test"),
        has_api_key=True,
        api_format="openai",
        protocol="openai",
        models=kwargs.get("models", ["deepseek-chat"]),
        enabled=True,
        sort_order=0,
    )


def test_sync_drops_stale_kimi_when_channel_switches_to_deepseek():
    """渠道改为 DeepSeek 后，逻辑模型与默认文本模型应落到 deepseek-chat。"""
    channels = [_channel(models=["deepseek-chat"])]
    stale = [
        LogicalModel(
            id="kimi-k2.6",
            name="kimi-k2.6",
            capability="text",
            enabled=True,
            bindings=[
                LogicalModelBinding(
                    id="openai-default:kimi-k2.6",
                    channel_id="openai-default",
                    upstream_model="kimi-k2.6",
                    enabled=True,
                    priority=1,
                )
            ],
        )
    ]
    synced = synchronize_logical_models_with_channels(stale, channels)
    defaults = normalize_default_models(
        DefaultModels(text_model="kimi-k2.6"),
        synced,
        channels,
    )
    assert [m.id for m in synced] == ["deepseek-chat"]
    assert defaults.text_model == "deepseek-chat"


def test_sync_keeps_binding_prefs_for_matching_upstream():
    """同名上游保留原绑定 priority / enabled。"""
    channels = [_channel(models=["deepseek-chat"])]
    existing = [
        LogicalModel(
            id="deepseek-chat",
            name="DeepSeek Chat",
            capability="text",
            enabled=True,
            bindings=[
                LogicalModelBinding(
                    id="openai-default:deepseek-chat",
                    channel_id="openai-default",
                    upstream_model="deepseek-chat",
                    enabled=True,
                    priority=3,
                    weight=80,
                )
            ],
        )
    ]
    synced = synchronize_logical_models_with_channels(existing, channels)
    assert len(synced) == 1
    assert synced[0].name == "DeepSeek Chat"
    assert synced[0].bindings[0].priority == 3
    assert synced[0].bindings[0].weight == 80
