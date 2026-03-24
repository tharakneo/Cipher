# Embed dialogue chunks and store in Qdrant

import json
from pathlib import Path

from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

CHUNKS_FILE = Path(__file__).parent / "data" / "chunks.json"
COLLECTION_NAME = "cipher"
VECTOR_SIZE = 384
BATCH_SIZE = 256


def make_id(movie: str, year: int, chunk_index: int) -> int:
    """Stable numeric ID from movie+year+chunk so re-runs are safe."""
    import hashlib

    key = f"{movie}|{year}|{chunk_index}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**63)


def main():
    chunks = json.loads(CHUNKS_FILE.read_text())
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_FILE}")

    client = QdrantClient(host="localhost", port=6333)

    existing_collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing_collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"Created collection '{COLLECTION_NAME}'")
        already_embedded: set[str] = set()
    else:
        # Find which movies are already in the collection — skip them
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=10_000,
            with_payload=["movie", "year"],
            with_vectors=False,
        )
        already_embedded = {
            f"{p.payload['movie']}|{p.payload['year']}" for p in result[0]
        }
        print(
            f"Collection exists — {len(already_embedded)} movies already embedded, skipping them"
        )

    new_chunks = [
        c for c in chunks if f"{c['movie']}|{c['year']}" not in already_embedded
    ]

    if not new_chunks:
        print("Nothing new to embed.")
        return

    print(
        f"Embedding {len(new_chunks)} new chunks ({len(chunks) - len(new_chunks)} skipped)..."
    )

    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [c["text"] for c in new_chunks]

    points = []
    for chunk, vector in zip(
        new_chunks,
        tqdm(
            model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True),
            total=len(texts),
            desc="Embedding",
        ),
    ):
        points.append(
            PointStruct(
                id=make_id(chunk["movie"], chunk["year"], chunk["chunk_index"]),
                vector=vector.tolist(),
                payload={
                    "movie": chunk["movie"],
                    "year": chunk["year"],
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                },
            )
        )

    for start in tqdm(range(0, len(points), BATCH_SIZE), desc="Upserting"):
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points[start : start + BATCH_SIZE],
        )

    print(f"\nDone — {len(points)} new chunks embedded into '{COLLECTION_NAME}'")


if __name__ == "__main__":
    main()
