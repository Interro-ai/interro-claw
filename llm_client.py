"""
Unified LLM client abstraction with:
- Claude / OpenAI / Ollama / NVIDIA NIM providers
- SQLite-backed response caching
- Exponential-backoff retry for transient failures
- Streaming response support (async generators)
- Guardrails integration (LLM call counting)
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import interro_claw.config as config

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 2.0
_RETRY_BACKOFF_FACTOR = 2.0


class BaseLLMClient(ABC):
    """Interface every provider must implement."""

    @abstractmethod
    async def _raw_chat(self, system_prompt: str, user_message: str) -> str:
        """Provider-specific chat call (no retry / caching)."""

    async def _raw_chat_stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        """Provider-specific streaming chat. Override for real streaming."""
        # Default: fall back to non-streaming and yield the full response
        result = await self._raw_chat(system_prompt, user_message)
        yield result

    async def chat(self, system_prompt: str, user_message: str) -> str:
        """Chat with caching + retry + guardrails. All providers get this for free.

        Cache strategy (inspired by code-review-graph):
        1. Exact-match cache (full prompt hash) — fastest
        2. Task-fingerprint cache (normalized task only) — catches rephrased questions
        3. On miss: call LLM, store in both exact + fingerprint caches
        """
        from interro_claw.guardrails import get_guardrails
        gr = get_guardrails()
        gr.increment_llm_calls()

        from interro_claw.memory import get_memory_store
        store = get_memory_store()
        if config.ENABLE_RESPONSE_CACHE:
            # Level 1: exact match
            cached = store.cache_get(system_prompt, user_message)
            if cached is not None:
                logger.info("LLM cache HIT (exact) — skipping API call")
                from interro_claw.telemetry import record as _trecord
                _trecord("cache_hits_exact")
                return cached

            # Level 2: task-fingerprint match (strips volatile context)
            tfp = store.task_fingerprint(user_message)
            cached = store.cache_get_normalized(tfp)
            if cached is not None:
                logger.info("LLM cache HIT (fingerprint) — skipping API call")
                from interro_claw.telemetry import record as _trecord
                _trecord("cache_hits_fingerprint")
                return cached

        from interro_claw.telemetry import record as _trecord
        _trecord("cache_misses")
        response = await self._chat_with_retry(system_prompt, user_message)

        if config.ENABLE_RESPONSE_CACHE:
            store.cache_put(
                system_prompt, user_message, response,
                ttl_seconds=config.CACHE_TTL_SECONDS,
            )
            # Also store by task fingerprint for future fuzzy hits
            store.cache_put_normalized(
                store.task_fingerprint(user_message), response,
                ttl_seconds=config.CACHE_TTL_SECONDS * 2,  # longer TTL for normalized
            )
        return response

    async def chat_stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        """Streaming chat — yields tokens as they arrive.

        Post-stream: assembles the full response and caches it, so the next
        identical request can skip the LLM call entirely.
        """
        from interro_claw.guardrails import get_guardrails
        gr = get_guardrails()
        gr.increment_llm_calls()

        # Check cache first — if hit, yield cached response as single chunk
        if config.ENABLE_RESPONSE_CACHE:
            from interro_claw.memory import get_memory_store
            store = get_memory_store()
            cached = store.cache_get(system_prompt, user_message)
            if cached is not None:
                logger.info("Stream cache HIT — returning cached response")
                yield cached
                return

        # Stream from LLM and collect for post-stream caching
        chunks: list[str] = []
        async for chunk in self._stream_with_retry(system_prompt, user_message):
            chunks.append(chunk)
            yield chunk

        # Cache the assembled response
        if config.ENABLE_RESPONSE_CACHE and chunks:
            full_response = "".join(chunks)
            from interro_claw.memory import get_memory_store
            store = get_memory_store()
            store.cache_put(
                system_prompt, user_message, full_response,
                ttl_seconds=config.CACHE_TTL_SECONDS,
            )

    @staticmethod
    def _extract_retry_after(exc: Exception) -> float | None:
        """Parse retry-after seconds from a 429 error message."""
        import re
        msg = str(exc)
        m = re.search(r"(?:try again in|retry after)\s+([\d.]+)\s*s", msg, re.IGNORECASE)
        if m:
            return float(m.group(1))
        return None

    async def _chat_with_retry(self, system_prompt: str, user_message: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._raw_chat(system_prompt, user_message)
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    # Honor OpenAI's retry-after for 429 errors
                    retry_after = self._extract_retry_after(exc)
                    if retry_after and "429" in str(exc):
                        delay = retry_after + 1.0  # add 1s buffer
                    else:
                        delay = _RETRY_BASE_DELAY * (_RETRY_BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, _MAX_RETRIES, exc, delay,
                    )
                    await asyncio.sleep(delay)
        raise RuntimeError(
            f"LLM call failed after {_MAX_RETRIES} attempts"
        ) from last_exc

    async def _stream_with_retry(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async for chunk in self._raw_chat_stream(system_prompt, user_message):
                    yield chunk
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    retry_after = self._extract_retry_after(exc)
                    if retry_after and "429" in str(exc):
                        delay = retry_after + 1.0
                    else:
                        delay = _RETRY_BASE_DELAY * (_RETRY_BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        "Stream failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, _MAX_RETRIES, exc, delay,
                    )
                    await asyncio.sleep(delay)
        raise RuntimeError(
            f"Stream failed after {_MAX_RETRIES} attempts"
        ) from last_exc


# -- Claude -----------------------------------------------------------------

class ClaudeClient(BaseLLMClient):
    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError("pip install anthropic") from exc
        if not config.CLAUDE_API_KEY:
            raise ValueError("CLAUDE_API_KEY is not set")
        self._client = anthropic.AsyncAnthropic(api_key=config.CLAUDE_API_KEY)
        self._model = config.CLAUDE_MODEL

    async def _raw_chat(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def _raw_chat_stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


# -- OpenAI -----------------------------------------------------------------

class OpenAIClient(BaseLLMClient):
    def __init__(self) -> None:
        try:
            import openai
        except ImportError as exc:
            raise ImportError("pip install openai") from exc
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set")
        self._client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self._model = config.OPENAI_MODEL

    async def _raw_chat(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    async def _raw_chat_stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=4096,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


# -- Ollama (local) ---------------------------------------------------------

class OllamaClient(BaseLLMClient):
    def __init__(self) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("pip install httpx") from exc
        self._base_url = config.OLLAMA_BASE_URL.rstrip("/")
        self._model = config.OLLAMA_MODEL

    async def _raw_chat(self, system_prompt: str, user_message: str) -> str:
        import httpx
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    async def _raw_chat_stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        import httpx
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content


# -- NVIDIA NIM (OpenAI-compatible API) --------------------------------------

class NvidiaClient(BaseLLMClient):
    """NVIDIA NIM cloud LLM via their OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        try:
            import openai
        except ImportError as exc:
            raise ImportError("pip install openai") from exc
        if not config.NVIDIA_API_KEY:
            raise ValueError("NVIDIA_API_KEY is not set")
        self._client = openai.AsyncOpenAI(
            base_url=config.NVIDIA_BASE_URL,
            api_key=config.NVIDIA_API_KEY,
        )
        self._model = config.NVIDIA_MODEL

    async def _raw_chat(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            top_p=0.7,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    async def _raw_chat_stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            top_p=0.7,
            max_tokens=4096,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


# ── Factory ───────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, type[BaseLLMClient]] = {
    "claude": ClaudeClient,
    "openai": OpenAIClient,
    "ollama": OllamaClient,
    "nvidia": NvidiaClient,
}


def get_llm_client(provider: str | None = None) -> BaseLLMClient:
    """Return an LLM client for the requested (or configured) provider."""
    provider = (provider or config.LLM_PROVIDER).lower()
    cls = _PROVIDERS.get(provider)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. "
            f"Choose from: {', '.join(_PROVIDERS)}"
        )
    logger.info("Initializing LLM client: %s", provider)
    return cls()
