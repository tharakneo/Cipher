"""
SubDL subtitle scraper.
Reads movies from scripts/data/movies.txt and downloads English SRT files.
"""

import io
import os
import re
import time
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("SUBDL_API_KEY")
DATA_DIR = Path(__file__).parent / "data"
MOVIES_TXT = DATA_DIR / "movies.txt"

API_URL = "https://api.subdl.com/api/v1/subtitles"
DL_BASE = "https://dl.subdl.com"
DELAY = 3  # seconds between requests


def movie_to_filename(name: str, year: int) -> str:
    """'The Dark Knight' 2008 → 'The_Dark_Knight_2008.srt'"""
    safe = re.sub(r"[^\w\s]", "", name).strip()
    safe = re.sub(r"\s+", "_", safe)
    return f"{safe}_{year}.srt"


def parse_movie_line(line: str) -> tuple[str, int]:
    """'Titanic 1997' → ('Titanic', 1997)"""
    line = line.strip()
    match = re.match(r"^(.+?)\s+(\d{4})$", line)
    if not match:
        raise ValueError(f"Cannot parse line: {line!r}")
    return match.group(1).strip(), int(match.group(2))


def fetch_subtitle_url(name: str, year: int) -> str | None:
    """Return the first subtitle ZIP URL for the movie, or None."""
    params = {
        "api_key": API_KEY,
        "film_name": name,
        "year": year,
        "type": "movie",
        "languages": "EN",
    }
    resp = requests.get(API_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    subtitles = data.get("subtitles") or []
    if not subtitles:
        return None
    return subtitles[0].get("url")


def download_srt(zip_url: str) -> bytes | None:
    """Download ZIP and return the first .srt file's contents."""
    full_url = f"{DL_BASE}{zip_url}" if zip_url.startswith("/") else zip_url
    resp = requests.get(full_url, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        srt_names = [n for n in zf.namelist() if n.lower().endswith(".srt")]
        if not srt_names:
            return None
        return zf.read(srt_names[0])


def main() -> None:
    if not API_KEY:
        raise SystemExit("❌ SUBDL_API_KEY not set in .env")

    lines = [l for l in MOVIES_TXT.read_text().splitlines() if l.strip()]
    print(f"Processing {len(lines)} movies...\n")

    ok = skipped = failed = 0

    for line in lines:
        try:
            name, year = parse_movie_line(line)
        except ValueError as e:
            print(f"❌  {e}")
            failed += 1
            continue

        out_path = DATA_DIR / movie_to_filename(name, year)

        if out_path.exists():
            print(f"⏭  {name} ({year}) — already exists")
            skipped += 1
            continue

        try:
            zip_url = fetch_subtitle_url(name, year)
            if not zip_url:
                print(f"❌  {name} ({year}) — no subtitles found")
                failed += 1
            else:
                srt_bytes = download_srt(zip_url)
                if not srt_bytes:
                    print(f"❌  {name} ({year}) — ZIP had no .srt file")
                    failed += 1
                else:
                    out_path.write_bytes(srt_bytes)
                    print(f"✅  {name} ({year}) → {out_path.name}")
                    ok += 1

        except Exception as e:
            print(f"❌  {name} ({year}) — {e}")
            failed += 1

        time.sleep(DELAY)

    print(f"\nDone — ✅ {ok}  ⏭ {skipped}  ❌ {failed}")


if __name__ == "__main__":
    main()
