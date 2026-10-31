"""Shared pytest configuration and audio fixtures."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTEST_QT_API", "pyside6")


@pytest.fixture(scope="session")
def audio_factory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate small silent audio files for metadata round-trip tests."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for audio fixture tests")

    root = tmp_path_factory.mktemp("audio")
    formats = {
        "flac": ["-c:a", "flac"],
        "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
        "m4a": ["-c:a", "aac", "-b:a", "128k"],
        "ogg": ["-c:a", "vorbis", "-strict", "-2"],
        "opus": ["-c:a", "libopus"],
        "wav": ["-c:a", "pcm_s16le"],
        "aiff": ["-c:a", "pcm_s16be"],
        "wv": ["-c:a", "wavpack"],
    }
    for extension, codec_args in formats.items():
        output = root / f"sample.{extension}"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "0.3",
            *codec_args,
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            pytest.skip(f"ffmpeg could not create {extension}: {result.stderr.strip()}")
    return root
