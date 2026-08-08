"""Provider interface plus Groq, Gemini and Mistral implementations, with a
cooldown-aware FallbackProvider chaining them together.

`generate()` is the only contract every provider honours, so FallbackProvider
is a drop-in replacement for any single provider at every call site.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

import requests

from .exceptions import AllProvidersRateLimitedError, LLMRateLimitError

DEFAULT_TRANSCRIBE_PROMPT = """Transcribe the text in this photo of a student's \
handwritten or printed economics answer, exactly as written.

Rules:
- Copy the words as they appear. Do not correct spelling, grammar, punctuation \
or economics content, and do not complete a sentence the student left unfinished.
- Preserve paragraph and line breaks where you can tell them apart.
- If a word is genuinely illegible, write [illegible] in its place rather than \
guessing a word that fits.
- Ignore margin doodles, crossed-out words, and anything that is not part of \
the final answer (unless the crossing-out itself is ambiguous, in which case \
leave the word in and note it was crossed out).
- Return ONLY the transcribed text. No preamble, no commentary, no markdown."""

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


class GeminiProvider:
    """Google Gemini via the official google-genai SDK.

    Uses the SDK rather than plain REST because Google AI Studio now issues
    "AQ."-prefix keys by default (instead of the older "AIzaSy..." format),
    and those keys are unreliable against the bare REST endpoint — they can
    401 or 404 depending on how the key is passed. The official SDK handles
    that quirk internally, so it works with both key formats.
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1500,
                 temperature: float = 0.2) -> LLMResponse:
        from google.genai import types
        from google.genai import errors as genai_errors

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )

        try:
            response = self._get_client().models.generate_content(
                model=self.model, contents=prompt, config=config,
            )
        except genai_errors.ClientError as exc:
            # Gemini 2.5-generation models use thinking_budget (an int),
            # Gemini 3.x-generation models use thinking_level (a string) —
            # they reject each other's parameter with a plain 400. Rather
            # than hardcode a generation, retry once with thinking left at
            # the model's own default (slightly more tokens spent, but works
            # on both generations) before treating it as a real failure.
            if getattr(exc, "code", None) == 400 or "INVALID_ARGUMENT" in str(exc):
                config.thinking_config = None
                try:
                    response = self._get_client().models.generate_content(
                        model=self.model, contents=prompt, config=config,
                    )
                except genai_errors.ClientError as retry_exc:
                    exc = retry_exc
                    response = None
            else:
                response = None

            if response is None:
                status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                text = str(exc)
                if status == 429 or "rate limit" in text.lower() or "resource_exhausted" in text.lower():
                    raise LLMRateLimitError(
                        text, provider=self.name,
                        retry_after_seconds=parse_retry_after(text) or 60.0,
                    ) from exc
                raise

        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            text=response.text or "",
            provider=self.name,
            model=self.model,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            completion_tokens=getattr(usage, "candidates_token_count", None),
        )

    def transcribe_image(
        self, image_bytes: bytes, mime_type: str, *, prompt: str | None = None
    ) -> LLMResponse:
        """Turn a photo of a handwritten/printed answer into plain text.

        This is a Gemini-only capability (Groq and Mistral's free tiers here
        are text-only), which is exactly why photo mode in the UI checks for
        GEMINI_API_KEY specifically rather than "any provider configured".
        """
        from google.genai import types
        from google.genai import errors as genai_errors

        config = types.GenerateContentConfig(max_output_tokens=2000, temperature=0.0)
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt or DEFAULT_TRANSCRIBE_PROMPT,
        ]

        try:
            response = self._get_client().models.generate_content(
                model=self.model, contents=contents, config=config,
            )
        except genai_errors.ClientError as exc:
            status = getattr(exc, "code", None)
            text = str(exc)
            if status == 429 or "rate limit" in text.lower() or "resource_exhausted" in text.lower():
                raise LLMRateLimitError(
                    text, provider=self.name,
                    retry_after_seconds=parse_retry_after(text) or 60.0,
                ) from exc
            raise

        return LLMResponse(text=(response.text or "").strip(), provider=self.name, model=self.model)


def transcribe_photo(settings, image_bytes: bytes, mime_type: str) -> str:
    """Convenience wrapper: build a Gemini provider from Settings and transcribe.

    Raises ValueError if GEMINI_API_KEY isn't set — callers (the essay page)
    check that ahead of time to give a clear explanation rather than let this
    exception surface as a raw stack trace.
    """
    if not getattr(settings, "gemini_api_key", None):
        raise ValueError("GEMINI_API_KEY is not set")
    provider = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    return provider.transcribe_image(image_bytes, mime_type).text


class MistralProvider:
    """Mistral's free-tier "La Plateforme" API, OpenAI-compatible REST."""

    name = "mistral"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("MISTRAL_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self._url = "https://api.mistral.ai/v1/chat/completions"

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1500,
                 temperature: float = 0.2) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = requests.post(
            self._url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60,
        )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise LLMRateLimitError(
                resp.text, provider=self.name,
                retry_after_seconds=float(retry_after) if retry_after else 60.0,
            )
        resp.raise_for_status()
        data = resp.json()

        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"] or "",
            provider=self.name,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


class FallbackProvider:
    """Tries providers in order, skipping any currently in cooldown.

    A rate limit on one provider puts *that provider* to sleep for its
    retry-after window (default 60s if unknown) and moves on to the next.
    The cooldown is remembered for the lifetime of this object, so a batch
    script generating many items in a loop won't keep re-hammering a
    provider that just told it to back off. Only raises
    AllProvidersRateLimitedError once every provider in the chain is either
    cooling down or itself rate-limited on this call.
    """

    name = "fallback"

    def __init__(self, providers: Sequence[LLMProvider]):
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        self._providers = list(providers)
        self._cooldown_until: dict[str, float] = {}

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1500,
                 temperature: float = 0.2) -> LLMResponse:
        notes: list[str] = []
        now = time.monotonic()

        for provider in self._providers:
            until = self._cooldown_until.get(provider.name)
            if until and now < until:
                notes.append(f"{provider.name}: cooling down {until - now:.0f}s more")
                continue
            try:
                response = provider.generate(
                    prompt, system=system,
                    max_tokens=max_tokens, temperature=temperature,
                )
            except LLMRateLimitError as exc:
                wait = exc.retry_after_seconds or 60.0
                self._cooldown_until[provider.name] = time.monotonic() + wait
                notes.append(f"{provider.name}: rate limited, {exc.friendly_wait()}")
                continue
            self._cooldown_until.pop(provider.name, None)
            return response

        raise AllProvidersRateLimitedError(
            "every provider is rate-limited or cooling down — " + "; ".join(notes)
        )


def build_provider(settings) -> LLMProvider:
    """Build a provider (or fallback chain) from Settings.

    Reads settings.llm_fallback_order (comma-separated, e.g. "groq,gemini,
    mistral") and wires up only the providers named there that also have an
    API key set. A provider named in the order but missing its key is
    skipped, not an error, so an .env with just GROQ_API_KEY still works
    even if LLM_FALLBACK_ORDER lists all three.
    """
    factories = {
        "groq": lambda: (
            GroqProvider(settings.groq_api_key, settings.groq_model)
            if settings.groq_api_key else None
        ),
        "gemini": lambda: (
            GeminiProvider(settings.gemini_api_key, settings.gemini_model)
            if getattr(settings, "gemini_api_key", None) else None
        ),
        "mistral": lambda: (
            MistralProvider(settings.mistral_api_key, settings.mistral_model)
            if getattr(settings, "mistral_api_key", None) else None
        ),
    }

    order = [name.strip().lower()
             for name in settings.llm_fallback_order.split(",") if name.strip()]

    providers: list[LLMProvider] = []
    for name in order:
        factory = factories.get(name)
        if factory is None:
            continue
        provider = factory()
        if provider is not None:
            providers.append(provider)

    if not providers:
        raise ValueError(
            "No LLM provider is configured. Set at least one of GROQ_API_KEY, "
            "GEMINI_API_KEY, MISTRAL_API_KEY and list it in LLM_FALLBACK_ORDER."
        )

    if len(providers) == 1:
        return providers[0]
    return FallbackProvider(providers)