"""Video-Analyse via Google Gemini Interactions API + Files API sowie Template-Fallback."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Protocol

from google import genai

from src.config.constants import (
    CANDIDATE_MODELS,
    GEMINI_FILE_MAX_WAIT_SECONDS,
    GEMINI_FILE_POLL_INTERVAL_SECONDS,
    LLM_MAX_ATTEMPTS,
    LLM_TIMEOUT_SECONDS,
    RETRY_BACKOFF_BASE_SECONDS,
    YOUTUBE_MAX_DESCRIPTION_LENGTH,
)
from src.config.settings import AppSettings
from src.domain.exceptions import LLMProviderError
from src.domain.models import UploadProfile, VideoQueueItem
from src.domain.schemas import GeneratedVideoMetadata, normalize_hashtag
from src.security.sanitization import sanitize_youtube_description, sanitize_youtube_title

logger = logging.getLogger(__name__)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class VideoMetadataGenerator(Protocol):
    """Abstrakte Schnittstelle für Video-Metadaten-Generatoren."""

    def generate(
        self,
        video_path: Path,
        video: VideoQueueItem,
        profile: UploadProfile,
    ) -> GeneratedVideoMetadata: ...


def _extract_interaction_text(interaction: Any) -> str:
    """Liest `output_text` oder verkettet Text-Blöcke aus `model_output`-Steps."""
    direct = str(getattr(interaction, "output_text", "") or "").strip()
    if direct:
        return direct

    parts: list[str] = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for block in getattr(step, "content", None) or []:
            if getattr(block, "type", None) == "text":
                txt = str(getattr(block, "text", "") or "").strip()
                if txt:
                    parts.append(txt)
    return "\n\n".join(parts).strip()


def _extract_file_state(file_obj: Any) -> str:
    state = getattr(file_obj, "state", None)
    if state is None:
        return ""
    name = getattr(state, "name", None)
    return str(name if name is not None else state).upper()


def compose_final_metadata(
    raw: GeneratedVideoMetadata,
    profile: UploadProfile,
    video: VideoQueueItem,
) -> GeneratedVideoMetadata:
    """Wendet manuelle Overrides, Pflicht-Hashtags (`#Shorts`), Footer und Limits an."""
    final_title = sanitize_youtube_title(video.title_override or raw.title)
    base_desc = (video.description_override or raw.description).strip()

    merged_hashtags: list[str] = []
    seen_hashtags: set[str] = set()
    source_hashtags = (
        list(video.hashtags_override) if video.hashtags_override else list(raw.hashtags)
    )
    for tag in [*profile.required_hashtags, *source_hashtags]:
        norm = normalize_hashtag(tag)
        if not norm:
            continue
        key = norm.lower()
        if key not in seen_hashtags:
            seen_hashtags.add(key)
            merged_hashtags.append(norm)

    desc_blocks: list[str] = [base_desc] if base_desc else []
    if profile.description_footer.strip():
        desc_blocks.append(profile.description_footer.strip())
    if merged_hashtags:
        hashtag_line = " ".join(merged_hashtags)
        if hashtag_line.lower() not in base_desc.lower():
            desc_blocks.append(hashtag_line)

    final_description = sanitize_youtube_description(
        "\n\n".join(desc_blocks)[:YOUTUBE_MAX_DESCRIPTION_LENGTH]
    )

    merged_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in [*profile.default_tags, *raw.tags, *(h.lstrip("#") for h in merged_hashtags)]:
        clean = tag.strip().lstrip("#")
        if not clean:
            continue
        key = clean.lower()
        if key not in seen_tags:
            seen_tags.add(key)
            merged_tags.append(clean[:40])

    return GeneratedVideoMetadata(
        title=final_title,
        description=final_description or final_title,
        hashtags=merged_hashtags[:15],
        tags=merged_tags[:20],
    )


class TemplateVideoMetadataGenerator:
    """Deterministischer Fallback-Generator ohne externe KI-Abhängigkeit."""

    def generate(
        self,
        video_path: Path,  # noqa: ARG002
        video: VideoQueueItem,
        profile: UploadProfile,
    ) -> GeneratedVideoMetadata:
        stem = Path(video.filename).stem.replace("_", " ").replace("-", " ").strip()
        date_hint = (video.recorded_at or "")[:10]
        base_title = stem or "Clip"
        title = f"{base_title} ({date_hint})" if date_hint and len(base_title) < 60 else base_title

        description = (
            f"Recorded on {date_hint}."
            if date_hint
            else f"Uploaded automatically with profile '{profile.display_name}'."
        )
        raw = GeneratedVideoMetadata(
            title=sanitize_youtube_title(title),
            description=description,
            hashtags=list(profile.required_hashtags),
            tags=list(profile.default_tags),
        )
        return compose_final_metadata(raw, profile, video)


class GeminiVideoMetadataGenerator:
    """Analysiert Videos multimodal mit Gemini Files API + Interactions API."""

    def __init__(
        self,
        settings: AppSettings,
        client: genai.Client | None = None,
    ) -> None:
        if not settings.has_gemini_configured and client is None:
            raise LLMProviderError("Kein gültiger GEMINI_API_KEY konfiguriert.")
        self._settings = settings
        self._client = client or self._create_client(settings.gemini_api_key)
        self._models = self._build_model_chain(settings)

    @staticmethod
    def _create_client(api_key: str) -> genai.Client:
        http_opts = {"timeout": int(LLM_TIMEOUT_SECONDS * 1000), "retry_options": {"attempts": 1}}
        try:
            return genai.Client(api_key=api_key, http_options=http_opts)
        except TypeError:
            return genai.Client(api_key=api_key)

    @staticmethod
    def _build_model_chain(settings: AppSettings) -> list[str]:
        candidates = [settings.gemini_model, *settings.allowed_models, *CANDIDATE_MODELS]
        chain: list[str] = []
        for model in candidates:
            clean = model.strip()
            if clean and clean not in chain:
                chain.append(clean)
        return chain

    def _upload_and_wait_active(self, video_path: Path, mime_type: str) -> Any:
        uploaded = self._client.files.upload(
            file=str(video_path),
            config={"mime_type": mime_type or "video/mp4"},
        )
        deadline = time.monotonic() + GEMINI_FILE_MAX_WAIT_SECONDS
        while True:
            state_name = _extract_file_state(uploaded)
            if state_name in {"ACTIVE", ""}:
                return uploaded
            if state_name == "FAILED":
                raise LLMProviderError(f"Gemini File-Processing fehlgeschlagen für '{video_path.name}'.")
            if time.monotonic() >= deadline:
                raise LLMProviderError(
                    f"Timeout beim Gemini Video-Processing nach {GEMINI_FILE_MAX_WAIT_SECONDS:.0f}s."
                )
            time.sleep(GEMINI_FILE_POLL_INTERVAL_SECONDS)
            uploaded = self._client.files.get(name=uploaded.name)

    def _safe_delete_uploaded_file(self, uploaded: Any) -> None:
        file_name = getattr(uploaded, "name", None)
        if not file_name:
            return
        try:
            self._client.files.delete(name=file_name)
        except Exception as exc:
            logger.warning("Gemini Temp-Datei '%s' konnte nicht gelöscht werden: %s", file_name, exc)

    def generate(
        self,
        video_path: Path,
        video: VideoQueueItem,
        profile: UploadProfile,
    ) -> GeneratedVideoMetadata:
        """Lädt das Video temporär zu Gemini hoch, erzeugt strukturiertes JSON und räumt auf."""
        uploaded = None
        try:
            uploaded = self._upload_and_wait_active(video_path, video.mime_type)
            prompt = self._build_prompt(video, profile)
            system_instruction = (
                f"You are a YouTube metadata expert. Write all output in language '{profile.language}'. "
                "Return strictly valid JSON matching the schema without angle brackets (< or >)."
            )

            last_exc: Exception | None = None
            for attempt in range(LLM_MAX_ATTEMPTS):
                model_name = self._models[attempt % len(self._models)]
                try:
                    interaction = self._client.interactions.create(
                        model=model_name,
                        input=[
                            {
                                "type": "video",
                                "uri": uploaded.uri,
                                "mime_type": getattr(uploaded, "mime_type", None)
                                or video.mime_type
                                or "video/mp4",
                            },
                            {"type": "text", "text": prompt},
                        ],
                        system_instruction=system_instruction,
                        response_format={
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": GeneratedVideoMetadata.model_json_schema(),
                        },
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                    raw_text = _JSON_FENCE_RE.sub("", _extract_interaction_text(interaction)).strip()
                    if not raw_text:
                        raise ValueError("Leere JSON-Antwort von Gemini erhalten.")
                    parsed = GeneratedVideoMetadata.model_validate_json(raw_text)
                    return compose_final_metadata(parsed, profile, video)
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "Gemini Video-Analyse (%s, Versuch %d/%d) fehlgeschlagen: %s",
                        model_name,
                        attempt + 1,
                        LLM_MAX_ATTEMPTS,
                        exc,
                    )
                    if attempt + 1 < LLM_MAX_ATTEMPTS:
                        time.sleep(RETRY_BACKOFF_BASE_SECONDS * (attempt + 1))

            raise LLMProviderError(f"Gemini Video-Analyse endgültig fehlgeschlagen: {last_exc}")
        finally:
            if uploaded is not None:
                self._safe_delete_uploaded_file(uploaded)

    @staticmethod
    def _build_prompt(video: VideoQueueItem, profile: UploadProfile) -> str:
        req_tags = ", ".join(profile.required_hashtags) if profile.required_hashtags else "none"
        return (
            f"{profile.ai_prompt.strip()}\n\n"
            f"Video context:\n"
            f"- Original filename: {video.filename}\n"
            f"- Recorded at: {video.recorded_at or 'unknown'}\n"
            f"- Duration (seconds): {video.duration_seconds or 'unknown'}\n"
            f"- Target language: {profile.language}\n"
            f"- Required hashtags to include: {req_tags}\n"
            f"Constraints: Title max 95 chars, no '<' or '>', hashtags as #Tag list."
        )
