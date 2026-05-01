import io

import torch
from PIL import Image
from qdrant_client import QdrantClient
from transformers import CLIPModel, CLIPProcessor

COLLECTION_NAME = "cipher_vision"
TOP_K = 20
MIN_SCORE = 0.70
DOMINANCE = 0.6

_client = QdrantClient(host="127.0.0.1", port=6333)
_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
_model.eval()


def _embed_image(image: Image.Image) -> list[float]:
    inputs = _processor(images=image, return_tensors="pt")
    with torch.no_grad():
        return (
            _model.get_image_features(**inputs).pooler_output.squeeze().numpy().tolist()
        )


def _vote(vectors: list[list[float]]) -> dict | None:
    movie_scores: dict[str, float] = {}
    movie_year: dict[str, int] = {}

    for vector in vectors:
        results = _client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=TOP_K,
            with_payload=True,
        )
        for hit in results.points:
            if hit.score < MIN_SCORE:
                continue
            movie = hit.payload["movie"]
            movie_scores[movie] = movie_scores.get(movie, 0) + hit.score
            movie_year[movie] = hit.payload["year"]

    if not movie_scores:
        return None

    total = sum(movie_scores.values())
    best_movie = max(movie_scores, key=lambda m: movie_scores[m])
    dominance = movie_scores[best_movie] / total

    print(f"[vision] weighted scores: {movie_scores}")
    print(f"[vision] {best_movie} dominance={dominance:.2%}")

    if dominance < DOMINANCE:
        print(f"[vision] ambiguous (dominance < {DOMINANCE:.0%}) — rejecting")
        return None

    best_score = (
        max(
            h.score
            for v in vectors
            for h in _client.query_points(
                collection_name=COLLECTION_NAME, query=v, limit=TOP_K, with_payload=True
            ).points
            if h.payload["movie"] == best_movie
        )
        if vectors
        else 0.0
    )

    return {
        "movie": best_movie,
        "year": movie_year[best_movie],
        "confidence": round(best_score * 100, 2),
    }


def search(image_bytes: bytes) -> dict | None:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    vector = _embed_image(image)

    print("[vision] top hits:")
    results = _client.query_points(
        collection_name=COLLECTION_NAME, query=vector, limit=TOP_K, with_payload=True
    )
    for hit in results.points[:10]:
        print(f"  {hit.score:.3f}  {hit.payload['movie']} ({hit.payload['year']})")

    return _vote([vector])
