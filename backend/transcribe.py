# Whisper STT logic — uses whisper.cpp with Metal acceleration

import os
import subprocess
import tempfile
from pathlib import Path

WHISPER_BIN = os.environ.get("WHISPER_BIN", "whisper-cli")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "models/ggml-small.bin")


def transcribe(audio_path: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        # Convert to 16kHz mono WAV (whisper.cpp requirement)
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", wav_path, "--no-timestamps", "-l", "en"],
            check=True,
            capture_output=True,
            text=True,
        )

        return result.stdout.strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)
