import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

import torch
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tqdm import tqdm
from transformers import CLIPModel, CLIPProcessor

COLLECTION_NAME = "cipher_vision"
VECTOR_SIZE = 512
BATCH_SIZE = 64
DEFAULT_FPS = 0.5


def make_id(movie: str, year: int, timestamp: float) -> int:
    key = f"{movie}|{year}|{timestamp:.2f}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**63)


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
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
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
        print(f"'{args.movie}' is already embedded. Skipping.")
        return

    print("Loading CLIP model...")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model.eval()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        print(f"Extracting frames at {args.fps} fps...")
        frames = extract_frames(args.url, args.fps, tmp_dir)
        print(f"Extracted {len(frames)} frames")

        points = []
        for frame_path, timestamp in tqdm(frames, desc="Embedding"):
            image = Image.open(frame_path).convert("RGB")
            inputs = processor(images=image, return_tensors="pt")
            with torch.no_grad():
                vector = (
                    model.get_image_features(**inputs)
                    .pooler_output.squeeze()
                    .numpy()
                    .tolist()
                )

            points.append(
                PointStruct(
                    id=make_id(args.movie, args.year, timestamp),
                    vector=vector,
                    payload={
                        "movie": args.movie,
                        "year": args.year,
                        "timestamp": timestamp,
                    },
                )
            )

        print(f"Upserting {len(points)} vectors...")
        for start in tqdm(range(0, len(points), BATCH_SIZE), desc="Upserting"):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[start : start + BATCH_SIZE],
            )

    print(f"Done — {args.movie} ({args.year}) with {len(points)} frames")


if __name__ == "__main__":
    main()
