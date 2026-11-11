"""Expose prose incrementally; retain JSON/fenced actions until full validation."""
from __future__ import annotations

from app.printfilm_studio.integration.llm_stream import MAX_RESPONSE_CHARS


class VisibleReplyBuffer:
    def __init__(self):
        self.raw = ''
        self.emitted = ''

    def push(self, chunk: str) -> str:
        self.raw += chunk
        if len(self.raw) > MAX_RESPONSE_CHARS:
            raise RuntimeError('LLM 回复超过大小限制')
        candidate = self.raw.lstrip()
        if candidate.startswith(('{', '[')):
            return ''
        # Prose may precede a bare JSON action. Hold from the first possible
        # structured payload, including delimiters split across transport chunks.
        # Ordinary code/links are released after the complete reply is parsed.
        boundary = min((candidate.find(char) for char in '`[{' if char in candidate), default=len(candidate))
        candidate = candidate[:boundary].rstrip()
        return self.remainder(candidate)

    def remainder(self, visible: str) -> str:
        if not visible.startswith(self.emitted):
            raise RuntimeError('LLM 可见回复与流式前缀不一致')
        delta = visible[len(self.emitted):]
        self.emitted = visible
        return delta
