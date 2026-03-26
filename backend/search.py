# Qdrant vector search logic

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

COLLECTION_NAME = "cipher"
TOP_K = 20
CONFIDENCE_THRESHOLD = 50.0

_client = QdrantClient(host="127.0.0.1", port=6333)
_model = SentenceTransformer("all-MiniLM-L6-v2")


def _split_sentences(text: str) -> list[str]:
    """Split transcript into sentences, filter short ones."""
    import re
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if len(p.strip().split()) >= 4]


def search(query: str) -> dict | None:
    """
    Split transcript into sentences, search each sentence, aggregate
    best score per movie across all sentences, return top match.
    """
    sentences = _split_sentences(query)
    if not sentences:
        sentences = [query]

    # Accumulate top hit per sentence per movie
    from collections import defaultdict
    hits_by_movie: dict[str, list[float]] = defaultdict(list)
    year_by_movie: dict[str, int] = {}

    for sentence in sentences:
        vector = _model.encode(sentence).tolist()
        response = _client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=TOP_K,
            with_payload=True,
        )
        # Only count the best hit per movie per sentence
        best_per_movie: dict[str, float] = {}
        for hit in response.points:
            movie = hit.payload["movie"]
            year  = hit.payload["year"]
            year_by_movie[movie] = year
            if movie not in best_per_movie or hit.score > best_per_movie[movie]:
                best_per_movie[movie] = hit.score
        for movie, score in best_per_movie.items():
            hits_by_movie[movie].append(score)

    if not hits_by_movie:
        return None

    # Score = sum of top-3 sentence hits per movie
    # Rewards movies that appear consistently across multiple sentences
    scores_by_movie: dict[str, float] = {}
    for movie, hit_list in hits_by_movie.items():
        top3_hits = sorted(hit_list, reverse=True)[:3]
        scores_by_movie[movie] = sum(top3_hits)

    # Show top 3 for debugging
    top3 = sorted(scores_by_movie.items(), key=lambda x: x[1], reverse=True)[:3]
    for m, sc in top3:
        print(f"[search] {m}: {sc*100:.1f}%")

    best_movie = top3[0][0]
    confidence = top3[0][1] * 100

    if confidence < CONFIDENCE_THRESHOLD:
        return None

    return {
        "movie": best_movie,
        "year": year_by_movie[best_movie],
        "confidence": round(confidence, 2),
    }
