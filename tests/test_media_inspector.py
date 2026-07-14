import json
import subprocess
from pathlib import Path

from hobby_anime.media_inspector import FfprobeInspector


class FakeRunner:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        payload = self.payloads.pop(0)
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")


def test_accepts_spanish_audio(tmp_path: Path) -> None:
    video = tmp_path / "episode.mkv"
    video.touch()
    runner = FakeRunner(
        [
            {
                "streams": [
                    {"codec_type": "audio", "tags": {"language": "jpn"}},
                    {"codec_type": "audio", "tags": {"language": "spa"}},
                ]
            }
        ]
    )

    result = FfprobeInspector(runner=runner).inspect(video)

    assert result.accepted is True
    assert result.audio_languages == ("jpn", "spa")


def test_accepts_full_spanish_subtitles_but_rejects_partial_track(tmp_path: Path) -> None:
    full = tmp_path / "full.mkv"
    partial = tmp_path / "partial.mkv"
    full.touch()
    partial.touch()
    full_runner = FakeRunner(
        [
            {
                "streams": [
                    {
                        "codec_type": "subtitle",
                        "tags": {"language": "spa", "title": "Español completo"},
                    }
                ]
            }
        ]
    )
    partial_runner = FakeRunner(
        [
            {
                "streams": [
                    {
                        "codec_type": "subtitle",
                        "tags": {"language": "spa", "title": "Signs & Songs"},
                    }
                ]
            }
        ]
    )

    accepted = FfprobeInspector(
        subtitle_exclude_terms=("signs", "songs"),
        runner=full_runner,
    ).inspect(full)
    rejected = FfprobeInspector(
        subtitle_exclude_terms=("signs", "songs"),
        runner=partial_runner,
    ).inspect(partial)

    assert accepted.accepted is True
    assert rejected.accepted is False


def test_requires_every_video_in_batch_to_pass(tmp_path: Path) -> None:
    (tmp_path / "episode-1.mkv").touch()
    (tmp_path / "episode-2.mkv").touch()
    runner = FakeRunner(
        [
            {
                "streams": [
                    {"codec_type": "subtitle", "tags": {"language": "spa"}}
                ]
            },
            {
                "streams": [
                    {"codec_type": "subtitle", "tags": {"language": "eng"}}
                ]
            },
        ]
    )

    result = FfprobeInspector(runner=runner).inspect(tmp_path)

    assert result.accepted is False
    assert "episode-2.mkv" in result.reason


def test_accepts_external_spanish_subtitle(tmp_path: Path) -> None:
    video = tmp_path / "episode.mkv"
    video.touch()
    (tmp_path / "episode.es.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n"
        "¿Por qué no me dijiste que la puerta estaba abierta?\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\n"
        "El camino de la montaña es largo, pero vamos a llegar.\n",
        encoding="utf-8",
    )
    runner = FakeRunner(
        [
            {
                "streams": [
                    {"codec_type": "audio", "tags": {"language": "jpn"}}
                ]
            }
        ]
    )

    result = FfprobeInspector(runner=runner).inspect(video)

    assert result.accepted is True


def test_rejects_mislabeled_external_subtitle(tmp_path: Path) -> None:
    video = tmp_path / "episode.mkv"
    video.touch()
    (tmp_path / "episode.es.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n"
        "The road through this mountain is long and dangerous.\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\n"
        "We should return home before the night arrives.\n",
        encoding="utf-8",
    )
    runner = FakeRunner(
        [
            {
                "streams": [
                    {"codec_type": "audio", "tags": {"language": "jpn"}}
                ]
            }
        ]
    )

    result = FfprobeInspector(runner=runner).inspect(video)

    assert result.accepted is False
