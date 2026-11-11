"""Stream OpenAI-compatible text responses using the existing managed model policy."""
from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from contextlib import aclosing
from collections.abc import AsyncIterator

import httpx

from app.services.llm_client import DEFAULT_MAX_TOKENS, prepare_chat_request

logger = logging.getLogger(__name__)
TEXT_WRITING_TIMEOUT = 180.0

MAX_RESPONSE_CHARS = 2_000_000


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    lines: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        if line.startswith('data:'):
            value = line[5:].removeprefix(' ')
            size += len(value)
            if size > MAX_RESPONSE_CHARS:
                raise RuntimeError('LLM 流式事件超过大小限制')
            lines.append(value)
        elif not line and lines:
            yield '\n'.join(lines)
            lines, size = [], 0
    if lines:
        yield '\n'.join(lines)


def _parse_chunk(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError('LLM 流式响应不是合法 JSON') from exc
    if not isinstance(data, dict) or data.get('error'):
        raise RuntimeError('LLM 流式服务返回错误')
    return data


async def _chat_completions_stream(
    system: str, user: str, *, model_id: str | None = None,
    temperature: float = .6, max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = 300.0,
) -> AsyncIterator[str]:
    url, headers, payload = prepare_chat_request(
        system, user, model_id=model_id, temperature=temperature, max_tokens=max_tokens,
    )
    payload['stream'] = True
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream('POST', url, headers=headers, json=payload) as response:
            if response.status_code >= 400:
                raise RuntimeError(f'LLM 流式服务错误 HTTP {response.status_code}')
            # Some compatible gateways ignore stream=True. Do not replay the
            # response as artificial token events, or leak reasoning_content.
            if 'application/json' in response.headers.get('content-type', ''):
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > MAX_RESPONSE_CHARS:
                        raise RuntimeError('LLM 响应超过大小限制')
                data = _parse_chunk(body.decode('utf-8'))
                choices = data.get('choices') or []
                choice = choices[0] if choices else {}
                if choice.get('finish_reason') not in (None, 'stop'):
                    raise RuntimeError('LLM 回复未完整结束，请缩短请求后重试')
                content = (choice.get('message') or {}).get('content')
                if not isinstance(content, str) or not content:
                    raise RuntimeError('LLM 未返回正文')
                yield content
                return
            finished = False
            received = 0
            async for raw in _sse_data(response):
                if raw.strip() == '[DONE]':
                    finished = True
                    break
                data = _parse_chunk(raw)
                for choice in data.get('choices') or []:
                    if choice.get('index', 0) != 0:
                        continue
                    reason = choice.get('finish_reason')
                    if reason is not None:
                        if reason != 'stop':
                            raise RuntimeError('LLM 回复未完整结束，请缩短请求后重试')
                        finished = True
                    content = (choice.get('delta') or {}).get('content')
                    if isinstance(content, str) and content:
                        received += len(content)
                        if received > MAX_RESPONSE_CHARS:
                            raise RuntimeError('LLM 回复超过大小限制')
                        yield content
                if finished:
                    break
            if not finished:
                raise RuntimeError('LLM 流式连接中断，回复未完整结束')
            if not received:
                raise RuntimeError('LLM 未返回正文')


async def chat_completions_stream(system: str, user: str, *, model_id: str | None = None,
                                  temperature: float = .6, max_tokens: int = DEFAULT_MAX_TOKENS,
                                  timeout: float = 300.0) -> AsyncIterator[str]:
    started, count = monotonic(), 0
    logger.info('LLM stream start model=%s input_chars=%s timeout=%ss', model_id or 'default',len(user),timeout)
    try:
        async with asyncio.timeout(timeout):
            async with aclosing(_chat_completions_stream(system,user,model_id=model_id,temperature=temperature,max_tokens=max_tokens,timeout=timeout)) as source:
                async for content in source:
                    if not count:
                        logger.info('LLM stream first content model=%s after=%.2fs',model_id or 'default',monotonic()-started)
                    count += len(content)
                    yield content
        logger.info('LLM stream complete model=%s chars=%s elapsed=%.2fs',model_id or 'default',count,monotonic()-started)
    except TimeoutError as exc:
        logger.warning('LLM stream timeout model=%s chars=%s elapsed=%.2fs',model_id or 'default',count,monotonic()-started)
        raise RuntimeError(f'文字模型响应超时（{timeout:g}秒），请更换模型或缩短要求后重试') from exc
