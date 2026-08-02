"""Minimal provider interface plus a Groq implementation.

Deliberately thin. The intent is to port the existing multi-provider fallback
chain (Groq -> Gemini -> Mistral -> custom, with response cache and cooldown)
in as a drop-in replacement for GroqProvider once the first real LLM feature
lands. `generate()` is the only contract to honour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .exceptions import LLMRateLimitError

# "Please try again in 11m7.872s"
_RETRY_RE = re.compile(r"try again in\s+(?:(\d+)m)?([\d.]+)s", re.IGNORECASE)


def parse_retry_after(message: str) -> float | None:
    m = _RETRY_RE.search(message or "")
    if not m:
        return None
    minutes = int(m.group(1) or 0)
    seconds = float(m.group(2))
    return minutes * 60 + seconds


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    name: str

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1500,
                 temperature: float = 0.2) -> LLMResponse: ...


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from groq import Groq

            self._client = Groq(api_key=self.api_key)
        return self._client

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1500,
                 temperature: float = 0.2) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            completion = self._get_client().chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001 - normalised below
            text = str(exc)
            status = getattr(exc, "status_code", None)
            # 429 quota, 413 request-too-large-on-TPM: both mean "fall through".
            if status in (429, 413) or "rate limit" in text.lower():
                raise LLMRateLimitError(
                    text, provider=self.name,
                    retry_after_seconds=parse_retry_after(text),
                ) from exc
            raise

        usage = getattr(completion, "usage", None)
        return LLMResponse(
            text=completion.choices[0].message.content or "",
            provider=self.name,
            model=self.model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
