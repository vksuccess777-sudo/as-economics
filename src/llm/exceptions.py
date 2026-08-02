"""LLM error types.

Kept structurally identical to the FRI provider layer so that chain can be
dropped in wholesale later without touching call sites here.
"""

from __future__ import annotations


class LLMError(RuntimeError):
    pass


class LLMRateLimitError(LLMError):
    """Provider refused the request due to a quota/rate limit."""

    def __init__(self, message: str, *, provider: str,
                 retry_after_seconds: float | None = None):
        super().__init__(message)
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds

    def friendly_wait(self) -> str:
        if self.retry_after_seconds is None:
            return "an unknown amount of time"
        total = round(self.retry_after_seconds)
        minutes, seconds = divmod(total, 60)
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


class AllProvidersRateLimitedError(LLMError):
    pass
