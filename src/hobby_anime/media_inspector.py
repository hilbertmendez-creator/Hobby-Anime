from __future__ import annotations

import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Callable

from hobby_anime.library import VIDEO_EXTENSIONS
from hobby_anime.models import MediaInspection

SPANISH_LANGUAGE_CODES = {
    "es",
    "es-419",
    "es-es",
    "spa",
    "spanish",
    "castellano",
    "latino",
}
SPANISH_SIDECAR_SUFFIXES = (
    ".es.srt",
    ".spa.srt",
    ".es-es.srt",
    ".es-419.srt",
    ".es.ass",
    ".spa.ass",
    ".es.ssa",
    ".spa.ssa",
)


class FfprobeInspector:
    def __init__(
        self,
        ffprobe_path: str = "ffprobe",
        subtitle_exclude_terms: tuple[str, ...] = (),
        timeout_seconds: int = 60,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.ffprobe_path = ffprobe_path
        self.subtitle_exclude_terms = tuple(
            _normalize(term) for term in subtitle_exclude_terms if term.strip()
        )
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run

    def inspect(self, content_path: Path) -> MediaInspection:
        files = _video_files(content_path)
        if not files:
            return MediaInspection(
                accepted=False,
                reason="No supported video files were found in the completed download",
            )

        audio_languages: set[str] = set()
        subtitle_languages: set[str] = set()
        failures: list[str] = []
        for path in files:
            accepted, audio, subtitles, reason = self._inspect_file(path)
            audio_languages.update(audio)
            subtitle_languages.update(subtitles)
            if not accepted:
                failures.append(f"{path.name}: {reason}")

        return MediaInspection(
            accepted=not failures,
            audio_languages=tuple(sorted(audio_languages)),
            subtitle_languages=tuple(sorted(subtitle_languages)),
            inspected_files=tuple(files),
            reason="; ".join(failures) if failures else "Spanish audio or full subtitles verified",
        )

    def _inspect_file(
        self,
        path: Path,
    ) -> tuple[bool, set[str], set[str], str]:
        completed = self.runner(
            [
                self.ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type:stream_tags=language,title",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown ffprobe error"
            raise RuntimeError(f"ffprobe failed for {path.name}: {detail}")

        try:
            streams = json.loads(completed.stdout or "{}").get("streams", [])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ffprobe returned invalid JSON for {path.name}") from exc

        audio_languages: set[str] = set()
        subtitle_languages: set[str] = set()
        full_spanish_subtitle = False
        for stream in streams:
            codec_type = str(stream.get("codec_type", "")).casefold()
            tags: dict[str, Any] = stream.get("tags") or {}
            language = _normalize_language(str(tags.get("language", "")))
            title = _normalize(str(tags.get("title", "")))
            if codec_type == "audio" and language:
                audio_languages.add(language)
            if codec_type == "subtitle" and language:
                subtitle_languages.add(language)
                if (
                    language in SPANISH_LANGUAGE_CODES
                    and not self._is_partial_subtitle(title)
                ):
                    full_spanish_subtitle = True

        spanish_audio = bool(audio_languages & SPANISH_LANGUAGE_CODES)
        spanish_sidecar = _has_spanish_sidecar(path)
        accepted = spanish_audio or full_spanish_subtitle or spanish_sidecar
        reason = (
            "Spanish audio or full subtitles verified"
            if accepted
            else "No Spanish audio or full subtitle track was detected"
        )
        return accepted, audio_languages, subtitle_languages, reason

    def _is_partial_subtitle(self, title: str) -> bool:
        return any(term and term in title for term in self.subtitle_exclude_terms)


def _video_files(content_path: Path) -> list[Path]:
    if not content_path.exists():
        raise FileNotFoundError(f"Completed download path does not exist: {content_path}")
    if content_path.is_file():
        return [content_path] if content_path.suffix.casefold() in VIDEO_EXTENSIONS else []
    return sorted(
        path
        for path in content_path.rglob("*")
        if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS
    )


def _normalize_language(value: str) -> str:
    return _normalize(value).replace(" ", "-")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _has_spanish_sidecar(video_path: Path) -> bool:
    return any(
        video_path.with_name(f"{video_path.stem}{suffix}").is_file()
        for suffix in SPANISH_SIDECAR_SUFFIXES
    )
