import pytest

from src.llm.exceptions import LLMRateLimitError
from src.llm.provider import parse_retry_after


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Rate limit reached. Please try again in 11m7.872s", 667.872),
        ("Please try again in 19m7.392s", 1147.392),
        ("Please try again in 43.5s", 43.5),
        ("no retry information here", None),
    ],
)
def test_retry_time_is_parsed_from_the_provider_message(message, expected):
    assert parse_retry_after(message) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (667.872, "11m 8s"),
        (1147.392, "19m 7s"),
        (43.5, "44s"),
        # Rounding must carry, not display "11m 60s".
        (659.6, "11m 0s"),
        (None, "an unknown amount of time"),
    ],
)
def test_friendly_wait_rounds_and_carries(seconds, expected):
    err = LLMRateLimitError("x", provider="groq", retry_after_seconds=seconds)
    assert err.friendly_wait() == expected
