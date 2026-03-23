import sys
from pathlib import Path

import httpx

TEST_AUDIO_DIR = Path(__file__).parent / "data" / "test_audio"
API_URL = "http://localhost:8000/identify"


def main():
    audio_files = sorted(
        f for f in TEST_AUDIO_DIR.glob("*") if f.suffix in {".mp3", ".wav"}
    )

    if not audio_files:
        print(f"No .mp3 or .wav files found in {TEST_AUDIO_DIR}")
        sys.exit(1)

    for audio_file in audio_files:
        print(f"Testing: {audio_file.name}")
        with audio_file.open("rb") as f:
            response = httpx.post(API_URL, files={"audio": (audio_file.name, f)})
        print(f"  Status : {response.status_code}")
        print(f"  Response: {response.json()}")
        print()


if __name__ == "__main__":
    main()
