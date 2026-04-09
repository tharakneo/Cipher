# Streaming availability lookup

import re
import httpx

_GQL_URL = "https://apis.justwatch.com/graphql"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}

_QUERY = """
{
  searchTitles(
    source: "CATALOG"
    country: US
    language: "en"
    first: 5
    filter: { searchQuery: "%s", objectTypes: [MOVIE] }
  ) {
    edges {
      node {
        content(country: US, language: "en") {
          title
          originalReleaseYear
        }
        offers(country: US, platform: WEB) {
          monetizationType
          package { technicalName }
          standardWebURL
        }
      }
    }
  }
}
"""


# ── deep link builders ────────────────────────────────────────────────────────


def _build_netflix(url: str) -> str:
    m = re.search(r"netflix\.com/title/(\d+)", url)
    return f"nflx://www.netflix.com/title/{m.group(1)}" if m else url


def _build_prime(url: str) -> str:
    m = re.search(r"gti=([\w.-]+)", url) or re.search(r"/dp/([A-Z0-9]+)", url)
    return f"aiv://aiv/play?asin={m.group(1)}" if m else url


def _build_max(url: str) -> str:
    # URLs are play.hbomax.com/show/{id} or max.com/...
    m = re.search(r"hbomax\.com/(show|movie)/([\w-]+)", url)
    if m:
        return f"max://{m.group(1)}/{m.group(2)}"
    path = re.sub(r"https?://(?:www\.)?max\.com", "", url)
    return f"max://{path.lstrip('/')}" if path else url


def _build_hulu(url: str) -> str:
    path = re.sub(r"https?://(?:www\.)?hulu\.com", "", url)
    return f"hulu://{path.lstrip('/')}" if path else url


def _build_appletv(url: str) -> str:
    # https://tv.apple.com/us/movie/title/umc.cmc.xxx
    path = re.sub(r"https?://tv\.apple\.com(?:/[a-z]{2})?", "", url)
    return f"videos://{path.lstrip('/')}" if path else url


# technicalName → (display name, deep link builder)
_PROVIDERS = {
    "netflix": ("Netflix", _build_netflix),
    "amazon_prime_video": ("Prime Video", _build_prime),
    "hbo_max": ("Max", _build_max),
    "max": ("Max", _build_max),
    "hulu": ("Hulu", _build_hulu),
    "apple_tv_plus": ("Apple TV+", _build_appletv),
    "appletvplus": ("Apple TV+", _build_appletv),
    "amazonappletvplus": ("Apple TV+", _build_appletv),
    "itunes": ("Apple TV+", _build_appletv),
}


# ── public API ────────────────────────────────────────────────────────────────


def get_streaming(movie: str, year: int) -> list[dict]:
    try:
        resp = httpx.post(
            _GQL_URL,
            headers=_HEADERS,
            json={"query": _QUERY % movie.replace('"', '\\"')},
            timeout=8,
        )
        resp.raise_for_status()
        edges = resp.json()["data"]["searchTitles"]["edges"]
    except Exception:
        return []

    # Find the right movie by year (±1 year tolerance)
    node = None
    for edge in edges:
        content = edge["node"]["content"]
        if abs((content.get("originalReleaseYear") or 0) - year) <= 1:
            node = edge["node"]
            break

    if not node:
        return []

    seen = set()
    results = []

    for offer in node.get("offers", []):
        if offer.get("monetizationType") not in ("FLATRATE", "FREE"):
            continue  # skip rentals and purchases

        tech = offer["package"]["technicalName"]
        if tech not in _PROVIDERS or tech in seen:
            continue

        platform_name, build_link = _PROVIDERS[tech]
        if platform_name in seen:
            continue
        web_url = offer.get("standardWebURL", "")
        deep_link = build_link(web_url) if web_url else ""

        results.append({"platform": platform_name, "deep_link": deep_link})
        seen.add(platform_name)

    return results
