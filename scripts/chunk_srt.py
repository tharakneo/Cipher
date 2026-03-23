import re
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = DATA_DIR / "chunks.json"
CHUNK_SIZE = 4
OVERLAP = 1


def parse_movie_info(filename: str) -> tuple[str, int]:
    stem = Path(filename).stem
    match = re.match(r"^(.+?)_(\d{4})$", stem)
    if not match:
        raise ValueError(f"Unexpected filename format: {filename}")
    name = match.group(1).replace("_", " ")
    year = int(match.group(2))
    return name, year


def clean_srt(content: str) -> list[str]:
    # Remove BOM if present
    content = content.lstrip("\ufeff")

    # Remove timing lines
    content = re.sub(r"\d+:\d+:\d+,\d+\s*-->\s*\d+:\d+:\d+,\d+", "", content)

    # Remove sequence numbers (lines with only digits)
    content = re.sub(r"^\d+\s*$", "", content, flags=re.MULTILINE)

    # Remove HTML tags
    content = re.sub(r"<[^>]+>", "", content)

    # Remove lines that are just sound effects / stage directions in brackets
    # (keep them stripped but still include as dialogue context)
    lines = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    return lines


def chunk_lines(lines: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(lines), step):
        segment = lines[i : i + chunk_size]
        if segment:
            chunks.append(" ".join(segment))
    return chunks


def process_all_srts() -> list[dict]:
    srt_files = sorted(DATA_DIR.glob("*.srt"))
    all_chunks = []
    total = 0

    for srt_path in srt_files:
        movie, year = parse_movie_info(srt_path.name)
        content = srt_path.read_text(encoding="utf-8", errors="replace")
        lines = clean_srt(content)
        chunks = chunk_lines(lines, CHUNK_SIZE, OVERLAP)

        for idx, text in enumerate(chunks):
            all_chunks.append(
                {
                    "movie": movie,
                    "year": year,
                    "chunk_index": idx,
                    "text": text,
                }
            )

        print(f"  {movie} ({year}): {len(chunks)} chunks")
        total += len(chunks)

    print(f"\nTotal chunks: {total}")
    return all_chunks


if __name__ == "__main__":
    chunks = process_all_srts()
    OUTPUT_FILE.write_text(json.dumps(chunks, indent=2, ensure_ascii=False))
    print(f"Written to {OUTPUT_FILE}")
