# Frequency + Fuzzy Match search logic

import re
from collections import Counter, defaultdict

from qdrant_client import QdrantClient
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer

COLLECTION_NAME = "cipher"
TOP_K = 20               # results per sentence in vector search
MAX_CANDIDATES = 10       # movies to fuzzy match against
FUZZY_THRESHOLD = 70      # minimum fuzzy score to count as a match
MIN_FUZZY_MATCHES = 1     # minimum sentences that must fuzzy match

_client = QdrantClient(host="127.0.0.1", port=6333)
_model = SentenceTransformer("all-MiniLM-L6-v2")


def _split_sentences(text: str) -> list[str]:
    """Split transcript into sentences, keep 3+ word ones."""
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if len(p.strip().split()) >= 3]


def _get_candidate_movies(sentences: list[str]) -> list[str]:
    """
    Step 1: Vector search each sentence, count how many sentences
    each movie appears in. Return top candidates by frequency.
    """
    movie_freq: Counter = Counter()
    year_by_movie: dict[str, int] = {}

    for sentence in sentences:
        vector = _model.encode(sentence).tolist()
        response = _client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=TOP_K,
            with_payload=True,
        )
        # Count each movie once per sentence (not per hit)
        seen = set()
        for hit in response.points:
            movie = hit.payload["movie"]
            year_by_movie[movie] = hit.payload["year"]
            if movie not in seen:
                movie_freq[movie] += 1
                seen.add(movie)

    # Top candidates by frequency
    candidates = [m for m, _ in movie_freq.most_common(MAX_CANDIDATES)]
    print(f"[search] candidates: {[(m, movie_freq[m]) for m in candidates]}")
    return candidates, year_by_movie


def _load_movie_text(movie: str) -> str:
    """Load all subtitle chunks for a movie from Qdrant, concatenate."""
    all_chunks = []
    offset = None
    while True:
        results, offset = _client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter={
                "must": [{"key": "movie", "match": {"value": movie}}]
            },
            limit=500,
            with_payload=True,
            offset=offset,
        )
        for pt in results:
            all_chunks.append((pt.payload.get("chunk_index", 0), pt.payload["text"]))
        if offset is None:
            break

    # Sort by chunk_index to reconstruct order
    all_chunks.sort(key=lambda x: x[0])
    return " ".join(text for _, text in all_chunks)


def _fuzzy_score(sentences: list[str], movie_text: str) -> tuple[int, float]:
    """
    Fuzzy match each sentence against a movie's full subtitle text.
    Returns (number of sentences matched above threshold, avg score of matches).
    """
    scores = []
    for sentence in sentences:
        score = fuzz.partial_ratio(sentence.lower(), movie_text.lower())
        scores.append(score)

    matches = [s for s in scores if s >= FUZZY_THRESHOLD]
    match_count = len(matches)
    avg_score = sum(matches) / len(matches) if matches else 0

    return match_count, avg_score


def search(query: str) -> dict | None:
    """
    1. Split transcript into sentences
    2. Vector search → pick candidate movies by frequency
    3. Fuzzy match each sentence against each candidate's full subtitle text
    4. Best movie = most sentences matched, tiebreak by avg fuzzy score
    """
    sentences = _split_sentences(query)
    if not sentences:
        sentences = [query]

    # Step 1: Get candidates via vector search frequency
    candidates, year_by_movie = _get_candidate_movies(sentences)

    if not candidates:
        return None

    # Step 2: Fuzzy match against each candidate
    results = []
    for movie in candidates:
        movie_text = _load_movie_text(movie)
        if not movie_text:
            continue
        match_count, avg_score = _fuzzy_score(sentences, movie_text)
        results.append((movie, match_count, avg_score))
        print(f"[fuzzy] {movie}: {match_count}/{len(sentences)} sentences matched, avg={avg_score:.1f}")

    if not results:
        return None

    # Sort by: match_count desc, then avg_score desc
    results.sort(key=lambda x: (x[1], x[2]), reverse=True)

    best_movie, best_count, best_avg = results[0]

    if best_count < MIN_FUZZY_MATCHES:
        print(f"[search] no movie passed fuzzy threshold")
        return None

    # Confidence = avg fuzzy score of matched sentences
    confidence = best_avg

    print(f"[search] winner: {best_movie} ({best_count}/{len(sentences)} matched, confidence={confidence:.1f}%)")

    return {
        "movie": best_movie,
        "year": year_by_movie.get(best_movie, 0),
        "confidence": round(confidence, 2),
    }
