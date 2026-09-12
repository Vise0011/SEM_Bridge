"""Normalization and prompt-injection detection for untrusted documents."""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SecurityFlag(StrEnum):
    """Machine-readable indicators found in untrusted source text."""

    PROMPT_OVERRIDE = "PROMPT_OVERRIDE"
    SYSTEM_PROMPT_REQUEST = "SYSTEM_PROMPT_REQUEST"
    TOOL_EXECUTION_REQUEST = "TOOL_EXECUTION_REQUEST"
    LOCAL_RESOURCE_REFERENCE = "LOCAL_RESOURCE_REFERENCE"
    SCRIPT_MARKUP = "SCRIPT_MARKUP"


class SanitizationError(ValueError):
    """Raised when source content exceeds a safe processing boundary."""


class SanitizedPassage(BaseModel):
    """Normalized text that remains explicitly untrusted."""

    model_config = ConfigDict(frozen=True)

    text: str
    trust_level: str = "UNTRUSTED_SOURCE"
    security_flags: list[SecurityFlag]


FLAG_PATTERNS: tuple[tuple[SecurityFlag, re.Pattern[str]], ...] = (
    (
        SecurityFlag.PROMPT_OVERRIDE,
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior)\s+instructions|"
            r"(이전|앞선)\s*(지시|명령).{0,12}무시",
            re.IGNORECASE,
        ),
    ),
    (
        SecurityFlag.SYSTEM_PROMPT_REQUEST,
        re.compile(r"system\s+prompt|시스템\s*프롬프트", re.IGNORECASE),
    ),
    (
        SecurityFlag.TOOL_EXECUTION_REQUEST,
        re.compile(
            r"(call|invoke|execute|run)\s+(the\s+)?(tool|command)|"
            r"(도구|명령어?).{0,12}(호출|실행)",
            re.IGNORECASE,
        ),
    ),
    (
        SecurityFlag.LOCAL_RESOURCE_REFERENCE,
        re.compile(r"file://|https?://(?:localhost|127\.0\.0\.1)(?::\d+)?", re.IGNORECASE),
    ),
    (SecurityFlag.SCRIPT_MARKUP, re.compile(r"<\s*script\b", re.IGNORECASE)),
)


def sanitize_untrusted_text(
    text: str,
    *,
    max_characters: int = 200_000,
) -> SanitizedPassage:
    """Remove unsafe control characters and flag instruction-like source content."""
    if len(text) > max_characters:
        raise SanitizationError("source passage exceeds the character limit")

    normalized = "".join(
        character
        for character in text.replace("\r\n", "\n").replace("\r", "\n")
        if character in {"\n", "\t"} or ord(character) >= 32
    ).strip()
    flags = [flag for flag, pattern in FLAG_PATTERNS if pattern.search(normalized)]
    return SanitizedPassage(text=normalized, security_flags=flags)
