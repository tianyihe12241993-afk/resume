"""Shared LLM client factory with a process-wide concurrency cap, supporting
both Anthropic and OpenAI behind ONE Anthropic-shaped interface.

Every module builds its client via `make_client()` and calls
`client.messages.create(model=, max_tokens=, temperature=, system=, messages=)`,
reading `resp.content[0].text` and `resp.usage.input_tokens/output_tokens`.

When LLM_PROVIDER=openai, `make_client()` returns a shim that translates that
call to OpenAI's chat.completions and wraps the response to look Anthropic-like,
so no call site changes. A global semaphore caps total in-flight requests
regardless of worker count, and clients carry a bounded timeout + retries.
"""
from __future__ import annotations

import threading

from . import config

_GATE = threading.BoundedSemaphore(max(1, config.ANTHROPIC_MAX_CONCURRENCY))


# ── OpenAI shim (Anthropic-compatible) ────────────────────────────────────

def _flatten_content(content) -> str:
    """Anthropic content is a string OR a list of blocks
    [{type:'text', text:'...', cache_control:...}]. Flatten to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n\n".join(parts)
    return str(content or "")


class _Block:
    __slots__ = ("type", "text")
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Usage:
    __slots__ = ("input_tokens", "output_tokens",
                 "cache_creation_input_tokens", "cache_read_input_tokens")
    def __init__(self, oai_usage):
        self.input_tokens = getattr(oai_usage, "prompt_tokens", 0) or 0
        self.output_tokens = getattr(oai_usage, "completion_tokens", 0) or 0
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _Resp:
    __slots__ = ("content", "usage")
    def __init__(self, oai_resp):
        text = (oai_resp.choices[0].message.content or "") if oai_resp.choices else ""
        self.content = [_Block(text)]
        self.usage = _Usage(getattr(oai_resp, "usage", None))


class _OpenAIShim:
    """Mimics anthropic.Anthropic over openai.OpenAI.chat.completions."""
    def __init__(self, api_key: str, timeout: float, max_retries: int):
        from openai import OpenAI
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set (LLM_PROVIDER=openai). Edit .env and restart."
            )
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.messages = self          # so client.messages.create(...) resolves here
        self.timeout = timeout
        self.max_retries = max_retries

    def create(self, *, model, messages, max_tokens=1024, temperature=0,
               system=None, **_ignored):
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": _flatten_content(system)})
        for m in messages:
            oai_messages.append({"role": m["role"], "content": _flatten_content(m.get("content"))})

        base = {"model": model, "messages": oai_messages}
        # Param names/limits vary across OpenAI model families. Try the common
        # gpt-4o shape first, then degrade for gpt-5/o-series (which use
        # max_completion_tokens and reject non-default temperature).
        attempts = [
            {"max_tokens": max_tokens, "temperature": temperature},
            {"max_completion_tokens": max_tokens, "temperature": temperature},
            {"max_completion_tokens": max_tokens},
        ]
        last_err = None
        for extra in attempts:
            try:
                return _Resp(self._client.chat.completions.create(**base, **extra))
            except Exception as e:
                msg = str(e).lower()
                if any(k in msg for k in ("max_tokens", "max_completion_tokens",
                                          "temperature", "unsupported", "unexpected")):
                    last_err = e
                    continue
                raise
        raise last_err


# ── Factory ───────────────────────────────────────────────────────────────

def make_client():
    """Provider-appropriate client whose `.messages.create` is wrapped with the
    global concurrency gate. Same interface for Anthropic and OpenAI."""
    if config.LLM_PROVIDER == "openai":
        client = _OpenAIShim(
            config.OPENAI_API_KEY, config.ANTHROPIC_TIMEOUT, config.ANTHROPIC_MAX_RETRIES,
        )
    else:
        from anthropic import Anthropic
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Edit .env and restart the server."
            )
        client = Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            timeout=config.ANTHROPIC_TIMEOUT,
            max_retries=config.ANTHROPIC_MAX_RETRIES,
        )

    _orig_create = client.messages.create

    def _gated_create(*args, **kwargs):
        with _GATE:
            return _orig_create(*args, **kwargs)

    client.messages.create = _gated_create
    return client
