"""Pydantic-Schemas für KI-generierte YouTube-Metadaten."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from src.config.constants import YOUTUBE_MAX_DESCRIPTION_LENGTH, YOUTUBE_MAX_TITLE_LENGTH

_ANGLE_BRACKETS_RE = re.compile(r"[<>]")
_WHITESPACE_RE = re.compile(r"\s+")
_HASHTAG_CLEAN_RE = re.compile(r"[^\w]", re.UNICODE)


def normalize_hashtag(raw_tag: str) -> str:
    """Normalisiert einen Hashtag auf `#Wort` ohne Leerzeichen oder Sonderzeichen."""
    stripped = _WHITESPACE_RE.sub("", raw_tag.strip()).lstrip("#")
    cleaned = _HASHTAG_CLEAN_RE.sub("", stripped)
    if not cleaned:
        return ""
    return f"#{cleaned}"


class GeneratedVideoMetadata(BaseModel):
    """Validiertes JSON-Schema für Gemini Video-Metadaten."""

    title: str = Field(..., min_length=3, max_length=YOUTUBE_MAX_TITLE_LENGTH)
    description: str = Field(..., min_length=5, max_length=YOUTUBE_MAX_DESCRIPTION_LENGTH)
    hashtags: list[str] = Field(default_factory=list, max_length=15)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: object) -> str:
        text = _ANGLE_BRACKETS_RE.sub("", str(value or ""))
        text = _WHITESPACE_RE.sub(" ", text).strip()
        if len(text) > YOUTUBE_MAX_TITLE_LENGTH:
            text = text[: YOUTUBE_MAX_TITLE_LENGTH - 1].rstrip() + "…"
        return text

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: object) -> str:
        text = _ANGLE_BRACKETS_RE.sub("", str(value or "")).strip()
        if len(text) > YOUTUBE_MAX_DESCRIPTION_LENGTH:
            text = text[:YOUTUBE_MAX_DESCRIPTION_LENGTH].rstrip()
        return text

    @field_validator("hashtags", mode="before")
    @classmethod
    def _clean_hashtags(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = normalize_hashtag(str(item))
            if not normalized:
                continue
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                result.append(normalized)
        return result[:15]

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            clean = _ANGLE_BRACKETS_RE.sub("", str(item)).strip().lstrip("#")
            clean = _WHITESPACE_RE.sub(" ", clean)
            if not clean:
                continue
            key = clean.lower()
            if key not in seen:
                seen.add(key)
                result.append(clean[:40])
        return result[:20]
