import io

import imagehash
from PIL import Image
from qdrant_client import QdrantClient

COLLECTION_NAME = "cipher_phash"
TOP_K = 20
HAMMING_THRESHOLD = 25  # bits different — lower = stricter match


_client = QdrantClient(host="127.0.0.1", port=6333)


def _phash_to_vector(h: imagehash.ImageHash) -> list[float]:
    bits = bin(int(str(h), 16))[2:].zfill(64)
    return [float(b) for b in bits]


def _hamming(h1: str, h2: str) -> int:
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def search(image_bytes: bytes) -> dict | None:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    query_hash = imagehash.phash(image)
    query_hash_str = str(query_hash)
    query_vector = _phash_to_vector(query_hash)

    results = _client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=TOP_K,
        with_payload=True,
    )

    if not results.points:
        return None

    # Re-rank by actual Hamming distance (Qdrant approximates, this is exact)
    candidates = []
    for hit in results.points:
        stored_hash = hit.payload.get("phash", "")
        if not stored_hash:
            continue
        dist = _hamming(query_hash_str, stored_hash)
        if dist <= HAMMING_THRESHOLD:
            candidates.append((dist, hit))

    print(f"[phash] query={query_hash_str}, {len(candidates)}/{TOP_K} within threshold")

    if not candidates:
        print(f"[phash] no match within Hamming threshold {HAMMING_THRESHOLD}")
        return None

    # Sort by Hamming distance, vote by movie
    candidates.sort(key=lambda x: x[0])

    from collections import Counter

    # Weight votes inversely by distance — closer = more votes
    vote_scores: dict[str, float] = {}
    for dist, hit in candidates:
        movie = hit.payload["movie"]
        weight = 1.0 / (dist + 1)  # dist=0 → weight=1.0, dist=10 → weight=0.09
        vote_scores[movie] = vote_scores.get(movie, 0) + weight

    best_movie = max(vote_scores, key=lambda m: vote_scores[m])

    print(f"[phash] vote_scores={vote_scores} → winner: {best_movie}")

    # Get best hit for that movie
    for dist, hit in candidates:
        if hit.payload["movie"] == best_movie:
            confidence = max(0.0, round((1 - dist / 64) * 100, 2))
            return {
                "movie": best_movie,
                "year": hit.payload["year"],
                "confidence": confidence,
            }
