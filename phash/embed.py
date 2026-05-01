# Extract frames from a movie URL and store pHash fingerprints in Qdrant
#
# Usage:
#   python -m vision.phash.embed --url "https://..." --movie "The Dark Knight" --year 2008
#   python -m vision.phash.embed --url "https://..." --movie "Inception" --year 2010 --fps 0.5

import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

import imagehash
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tqdm import tqdm

COLLECTION_NAME = "cipher_phash"
# pHash is 64 bits — store as 64-dim binary vector (each bit = one dimension)
VECTOR_SIZE = 64
BATCH_SIZE = 256
DEFAULT_FPS = 0.5  # 1 frame every 2 seconds


def make_id(movie: str, year: int, timestamp: float) -> int:
    key = f"{movie}|{year}|{timestamp:.2f}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**63)


def phash_to_vector(h: imagehash.ImageHash) -> list[float]:
    """Convert 64-bit pHash to a list of 64 floats (0.0 or 1.0) for Qdrant storage."""
    bits = bin(int(str(h), 16))[2:].zfill(64)
    return [float(b) for b in bits]


def extract_frames(url: str, fps: float, out_dir: Path) -> list[tuple[Path, float]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%06d.jpg")

    subprocess.run(
        [
            "ffmpeg",
            "-hwaccel",
            "videotoolbox",
            "-i",
            url,
            "-vf",
            f"fps={fps}",
            "-q:v",
            "3",
            pattern,
            "-y",
            "-loglevel",
            "error",
        ],
        check=True,
    )

    frames = sorted(out_dir.glob("frame_*.jpg"))
    interval = 1.0 / fps
    return [(f, i * interval) for i, f in enumerate(frames)]


def setup_collection(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.EUCLID),
        )
        print(f"Created collection '{COLLECTION_NAME}'")


def get_already_embedded(client: QdrantClient) -> set[str]:
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=100_000,
        with_payload=["movie", "year"],
        with_vectors=False,
    )
    return {f"{p.payload['movie']}|{p.payload['year']}" for p in result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--movie", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    args = parser.parse_args()

    client = QdrantClient(host="localhost", port=6333)
    setup_collection(client)

    already_embedded = get_already_embedded(client)
    key = f"{args.movie}|{args.year}"
    if key in already_embedded:
        print(f"'{args.movie}' already embedded. Skipping.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        print(f"Extracting frames at {args.fps} fps...")
        frames = extract_frames(args.url, args.fps, tmp_dir)
        print(f"{len(frames)} frames extracted")

        points = []
        skipped = 0
        for frame_path, timestamp in tqdm(frames, desc="Hashing"):
            image = Image.open(frame_path).convert("RGB")
            h = imagehash.phash(image)

            # Skip near-black/blank frames (hash ~= all zeros)
            if int(str(h), 16) < 1000:
                skipped += 1
                continue

            points.append(
                PointStruct(
                    id=make_id(args.movie, args.year, timestamp),
                    vector=phash_to_vector(h),
                    payload={
                        "movie": args.movie,
                        "year": args.year,
                        "timestamp": timestamp,
                        "phash": str(h),
                    },
                )
            )

        print(f"Skipped {skipped} blank frames")
        print(f"Upserting {len(points)} hashes to Qdrant...")
        for start in tqdm(range(0, len(points), BATCH_SIZE), desc="Upserting"):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[start : start + BATCH_SIZE],
            )

    print(
        f"\nDone — '{args.movie} ({args.year})' stored with {len(points)} frame hashes."
    )


if __name__ == "__main__":
    main()
