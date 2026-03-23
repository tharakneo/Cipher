# Whisper STT logic

import whisper

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = whisper.load_model("base")
    return _model


def transcribe(audio_path: str) -> str:
    result = _get_model().transcribe(audio_path, language="en")
    return result["text"].strip()
