"""Image, stock and avatar adapters.

Pollinations: free, no key; the image is generated when the URL is first fetched, so we
fetch it server-side with a long timeout and store the bytes.
Pexels / Pixabay: keyed stock search, cached 24 h in SQLite (Pixabay requires caching and
forbids hotlinking), attribution kept with every result.
"""

import hashlib
import json
import random
import time
import urllib.parse

from .. import db
from .base import KeySpec, Provider, ProviderError, http

PEXELS_KEY = KeySpec("apiKey", "Pexels API key", "https://www.pexels.com/api/")
PIXABAY_KEY = KeySpec("apiKey", "Pixabay API key", "https://pixabay.com/api/docs/")
CACHE_TTL_S = 24 * 3600


def pollinations_url(prompt: str, width: int, height: int, seed: int | None = None, model: str = "flux") -> str:
    seed = seed if seed is not None else random.randint(0, 999_999)
    return (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
            f"?width={width}&height={height}&seed={seed}&nologo=true&model={model}")


def pollinations_generate(prompt: str, keys: dict, width: int = 1280, height: int = 720, seed: int | None = None) -> dict:
    url = pollinations_url(prompt, width, height, seed)
    resp = http("GET", url, "Pollinations", timeout=180)
    if not resp.headers.get("content-type", "").startswith("image/"):
        raise ProviderError("bad_output", "Pollinations: image नहीं मिली।")
    return {"bytes": resp.content, "mime": resp.headers["content-type"], "source_url": url,
            "attribution": "Image: Pollinations.ai (AI-generated)"}


def _cache_get(provider: str, key: str):
    h = hashlib.sha256(key.encode()).hexdigest()
    with db.locked() as c:
        row = c.execute("SELECT response_json, fetched_at FROM stock_cache WHERE provider=? AND query_hash=?", (provider, h)).fetchone()
    if row and time.time() - row["fetched_at"] < CACHE_TTL_S:
        return json.loads(row["response_json"])
    return None


def _cache_put(provider: str, key: str, value) -> None:
    h = hashlib.sha256(key.encode()).hexdigest()
    with db.locked() as c:
        c.execute("INSERT OR REPLACE INTO stock_cache(provider, query_hash, response_json, fetched_at) VALUES (?,?,?,?)",
                  (provider, h, json.dumps(value), time.time()))


def pexels_search(query: str, keys: dict, kind: str = "photo", per_page: int = 5) -> list[dict]:
    cache_key = f"{kind}|{query}|{per_page}"
    cached = _cache_get("pexels", cache_key)
    if cached is not None:
        return cached
    base = "https://api.pexels.com/videos/search" if kind == "video" else "https://api.pexels.com/v1/search"
    data = http("GET", base, "Pexels", params={"query": query, "per_page": per_page},
                headers={"Authorization": keys["apiKey"]}).json()
    out = []
    if kind == "video":
        for v in data.get("videos", []):
            files = sorted(v.get("video_files", []), key=lambda f: abs((f.get("height") or 0) - 720))
            if files:
                out.append({"kind": "video", "url": files[0]["link"], "width": files[0].get("width"),
                            "height": files[0].get("height"), "duration": v.get("duration"),
                            "page": v.get("url"), "attribution": f"Video by {v.get('user', {}).get('name', 'unknown')} on Pexels"})
    else:
        for p in data.get("photos", []):
            out.append({"kind": "photo", "url": p["src"].get("large2x") or p["src"].get("original"),
                        "width": p.get("width"), "height": p.get("height"), "page": p.get("url"),
                        "attribution": f"Photo by {p.get('photographer', 'unknown')} on Pexels"})
    _cache_put("pexels", cache_key, out)
    return out


def pixabay_search(query: str, keys: dict, kind: str = "photo", per_page: int = 5) -> list[dict]:
    cache_key = f"{kind}|{query}|{per_page}"
    cached = _cache_get("pixabay", cache_key)
    if cached is not None:
        return cached
    base = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
    # Pixabay only accepts the key as a query parameter; this outbound URL is never logged.
    data = http("GET", base, "Pixabay", params={"key": keys["apiKey"], "q": query, "per_page": max(3, per_page),
                                               "safesearch": "true"}).json()
    out = []
    for h in data.get("hits", []):
        if kind == "video":
            vids = h.get("videos", {})
            pick = vids.get("medium") or vids.get("small") or vids.get("large") or {}
            if pick.get("url"):
                out.append({"kind": "video", "url": pick["url"], "width": pick.get("width"), "height": pick.get("height"),
                            "duration": h.get("duration"), "page": h.get("pageURL"),
                            "attribution": f"Video by {h.get('user', 'unknown')} on Pixabay"})
        else:
            out.append({"kind": "photo", "url": h.get("largeImageURL") or h.get("webformatURL"), "width": h.get("imageWidth"),
                        "height": h.get("imageHeight"), "page": h.get("pageURL"),
                        "attribution": f"Image by {h.get('user', 'unknown')} on Pixabay"})
    _cache_put("pixabay", cache_key, out)
    return out


def _pexels_health(keys):
    http("GET", "https://api.pexels.com/v1/search", "Pexels", params={"query": "test", "per_page": 1},
         headers={"Authorization": keys["apiKey"]})


def _pixabay_health(keys):
    http("GET", "https://pixabay.com/api/", "Pixabay", params={"key": keys["apiKey"], "q": "test", "per_page": 3})


PROVIDERS = [
    Provider("pollinations", "Pollinations.ai", "image", "free", [], "बिना key; शर्तें verify नहीं (2026-10)।",
             "https://pollinations.ai", priority=10, impl=pollinations_generate),
    Provider("wikimedia", "Wikimedia Commons", "image", "free", [], "बिना key; attribution ज़रूरी।",
             "https://commons.wikimedia.org", priority=20, enabled=False, note="वैकल्पिक — Phase 3 में।"),
    Provider("pexels", "Pexels", "stock", "free", [PEXELS_KEY], "Attribution ज़रूरी (2026-10)।",
             "https://www.pexels.com/api/", priority=10, health_fn=_pexels_health, impl=pexels_search),
    Provider("pixabay", "Pixabay", "stock", "free", [PIXABAY_KEY], "24 घंटे cache ज़रूरी, hotlinking मना (2026-10)।",
             "https://pixabay.com/api/docs/", priority=20, health_fn=_pixabay_health, impl=pixabay_search),
    Provider("avatar_2d", "2D cartoon avatar (built-in)", "avatar", "free", [], "स्थानीय रेंडर, बिना key।",
             "", priority=10, note="Phase 3 में बनेगा।"),
    Provider("lipsync_avatar", "Realistic lip-sync avatar", "avatar", "premium", [], "Price unverified.",
             "", priority=90, enabled=False, note="जल्द आ रहा है (MVP 2)।"),
]
