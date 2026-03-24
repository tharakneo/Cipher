import os
import httpx
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("TMDB_API_KEY")
_BASE = "https://api.themoviedb.org/3"
_IMG = "https://image.tmdb.org/t/p/w500"


def get_movie_details(movie: str, year: int) -> dict:
    try:
        resp = httpx.get(
            f"{_BASE}/search/movie",
            params={"api_key": _API_KEY, "query": movie, "year": year},
            timeout=6,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return {}

        r = results[0]
        movie_id = r["id"]

        genres = []
        if r.get("genre_ids"):
            genres = _fetch_genres(r["genre_ids"])

        logo_url = _fetch_logo(movie_id)

        backdrop_url = (
            f"https://image.tmdb.org/t/p/w780{r['backdrop_path']}"
            if r.get("backdrop_path")
            else None
        )

        return {
            "poster_url": f"{_IMG}{r['poster_path']}" if r.get("poster_path") else None,
            "backdrop_url": backdrop_url,
            "logo_url": logo_url,
            "synopsis": r.get("overview") or None,
            "rating": round(r.get("vote_average", 0), 1),
            "genres": genres,
        }
    except Exception:
        return {}


def _fetch_logo(movie_id: int) -> str | None:
    try:
        resp = httpx.get(
            f"{_BASE}/movie/{movie_id}/images",
            params={"api_key": _API_KEY, "include_image_language": "en,null"},
            timeout=6,
        )
        resp.raise_for_status()
        logos = resp.json().get("logos", [])
        if not logos:
            return None
        # prefer English logo, pick highest vote_average
        logos.sort(key=lambda x: x.get("vote_average", 0), reverse=True)
        return f"https://image.tmdb.org/t/p/w500{logos[0]['file_path']}"
    except Exception:
        return None


def _fetch_genres(genre_ids: list[int]) -> list[str]:
    try:
        resp = httpx.get(
            f"{_BASE}/genre/movie/list",
            params={"api_key": _API_KEY},
            timeout=6,
        )
        resp.raise_for_status()
        genre_map = {g["id"]: g["name"] for g in resp.json().get("genres", [])}
        return [genre_map[gid] for gid in genre_ids if gid in genre_map]
    except Exception:
        return []
