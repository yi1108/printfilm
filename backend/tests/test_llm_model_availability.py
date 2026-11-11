"""Managed text model switches must also block legacy environment requests."""

import json

import httpx
import pytest

from app.config import Settings
from app.schemas_routing import DefaultModels, LogicalModel, LogicalModelBinding, SystemModelChannel
from app.services import llm_client
from app.services.model_settings import RoutingSnapshot


@pytest.fixture
def text_client(monkeypatch):
    settings = Settings(_env_file=None, debug=False, openai_api_key="environment-key",
                        openai_base_url="https://environment.test/v1", model_llm="kimi-k2.6")
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "model response"}}]})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs))

    def configure(*, managed=True, enabled=True, binding_enabled=True, default=True):
        channel = SystemModelChannel(id="alpha", name="Alpha", base_url="https://channel.test/v1",
            api_key="channel-key", has_api_key=True, models=["kimi-k2.6"])
        model = LogicalModel(id="kimi-k2.6", capability="text", enabled=enabled, bindings=[
            LogicalModelBinding(channel_id=channel.id, upstream_model="kimi-k2.6", enabled=binding_enabled),
        ])
        snapshot = RoutingSnapshot(channels=[channel] if managed else [],
            logical_models=[model] if managed else [],
            default_models=DefaultModels(text_model=model.id if managed and default else ""))
        monkeypatch.setattr("app.services.model_settings._routing_snapshot", snapshot)

    return configure, requests


@pytest.mark.parametrize("options", [
    {"enabled": False},
    {"default": False},
    {"binding_enabled": False},
], ids=["disabled-model", "empty-managed-default", "disabled-bindings"])
@pytest.mark.parametrize('streaming', [False, True])
async def test_managed_text_unavailable_never_uses_environment_credentials(text_client, options, streaming):
    configure, requests = text_client
    configure(**options)

    with pytest.raises(llm_client.LlmUnavailableError):
        if streaming:
            from app.printfilm_studio.integration.llm_stream import chat_completions_stream
            _ = [chunk async for chunk in chat_completions_stream("system", "user")]
        else:
            await llm_client.chat_completions("system", "user")

    assert requests == []


async def test_unmanaged_text_keeps_environment_compatibility(text_client):
    configure, requests = text_client
    configure(managed=False)

    assert await llm_client.chat_completions("system", "user") == "model response"

    assert len(requests) == 1
    assert str(requests[0].url) == "https://environment.test/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer environment-key"
    assert json.loads(requests[0].content)["model"] == "kimi-k2.6"


async def test_enabled_managed_text_uses_channel_credentials(text_client):
    configure, requests = text_client
    configure()

    assert await llm_client.chat_completions("system", "user") == "model response"

    assert len(requests) == 1
    assert str(requests[0].url) == "https://channel.test/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer channel-key"
