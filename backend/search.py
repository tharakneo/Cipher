# Qdrant vector search logic

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

COLLECTION_NAME = "cipher"
TOP_K = 10
CONFIDENCE_THRESHOLD = 50.0

_client = QdrantClient(host="127.0.0.1", port=6333)
_model = SentenceTransformer("all-MiniLM-L6-v2")


def search(query: str) -> dict | None:
    """
    Embed query, retrieve top-10 chunks from Qdrant, group by movie,
    sum similarity scores, and return the best match with confidence.

    Returns:
        {"movie": str, "year": int, "confidence": float}
        or None if confidence is below threshold.
    """
    vector = _model.encode(query).tolist()

    response = _client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=TOP_K,
        with_payload=True,
    )
    results = response.points

    if not results:
        return None

    # Group scores by movie — keep only the best hit per movie
    scores_by_movie: dict[str, float] = {}
    year_by_movie: dict[str, int] = {}

    for hit in results:
        movie = hit.payload["movie"]
        year = hit.payload["year"]
        if movie not in scores_by_movie or hit.score > scores_by_movie[movie]:
            scores_by_movie[movie] = hit.score
        year_by_movie[movie] = year

    best_movie = max(scores_by_movie, key=lambda m: scores_by_movie[m])
    confidence = scores_by_movie[best_movie] * 100  # cosine similarity → %

    if confidence < CONFIDENCE_THRESHOLD:
        return None

    return {
        "movie": best_movie,
        "year": year_by_movie[best_movie],
        "confidence": round(confidence, 2),
    }
