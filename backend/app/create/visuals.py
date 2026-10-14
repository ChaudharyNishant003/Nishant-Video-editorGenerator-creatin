"""Visuals per scene (PRD §5.3 step 5, §11.5).

Order per requested kind (all free; keyed providers are used only when their key is saved):
  stock_video / stock_image → Pexels → Pixabay → Wikimedia → Pollinations
  wiki_image                → Wikimedia → Pollinations
  ai_image                  → Pollinations → Wikimedia
Search results are cached 24 h (stock_cache table; Pixabay requires it), files are downloaded into the
project (no hotlinking) and every item keeps its attribution. When nothing works the scene falls back
to `avatar_only` with a visible notice — the video is still produced.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Callable

import requests

from ..providers import registry
from ..providers.base import ProviderError
from ..providers.media import pollinations_generate
from ..render.probe import probe
from ..render.translit import to_roman

MAX_BYTES = 120 * 1024 * 1024
AI_STYLE = ", educational documentary illustration, detailed, soft light, family friendly, no text, no watermark"
AI_RETRIES = 3
AI_PACE_S = 20.0           # Pollinations' anonymous tier allows about one image per ~30 s per IP (measured 2026-10-14)
_ai_last = {"t": 0.0}
AI_SIZE = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}


def _download(url: str, dest: Path) -> Path:
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "AIYTStudio/2.0"}) as r:
            r.raise_for_status()
            size = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ProviderError("error", "फ़ाइल बहुत बड़ी है।")
                    f.write(chunk)
    except requests.RequestException as e:
        tmp.unlink(missing_ok=True)
        raise ProviderError("transient", f"डाउनलोड नहीं हो सका ({type(e).__name__}).")
    tmp.replace(dest)
    try:
        info = probe(dest)
    except ValueError:
        info = None
    if not info or not info["has_video"]:
        dest.unlink(missing_ok=True)
        raise ProviderError("bad_output", "डाउनलोड की गई फ़ाइल image/video नहीं है।")
    return dest


def _stock(query: str, prefer: str, variant: int, dest: Path, all_keys: dict, preferred: str | None,
           notify: Callable[[str], None]) -> dict:
    kinds = ("video", "photo") if prefer == "stock_video" else ("photo", "video")

    def call(p, keys):
        for kind in kinds:
            items = p.impl(query, keys, kind=kind, per_page=5)
            if items:
                item = items[variant % len(items)]
                ext = ".mp4" if kind == "video" else ".jpg"
                path = dest / ("stock_" + hashlib.sha256(item["url"].encode()).hexdigest()[:16] + ext)
                if not path.is_file():
                    _download(item["url"], path)
                return {"path": str(path), "attribution": item.get("attribution") or p.label, "provider": p.id,
                        "media": kind, "page": item.get("page")}
        raise ProviderError("bad_output", f"{p.label}: '{query}' के लिए कुछ नहीं मिला।")

    res, _ = registry.run_with_fallback("stock", preferred, all_keys, call, notify=notify)
    return res


def _wiki(query: str, variant: int, dest: Path) -> dict:
    p = registry.get("wikimedia")
    items = p.impl(query, {})
    if not items:
        raise ProviderError("bad_output", f"Wikimedia: '{query}' के लिए तस्वीर नहीं मिली।")
    last: ProviderError | None = None
    for k in range(min(3, len(items))):  # a single failing download must not lose the scene
        item = items[(variant + k) % len(items)]
        ext = ".png" if item["url"].lower().split("?")[0].endswith(".png") else ".jpg"
        path = dest / ("wiki_" + hashlib.sha256(item["url"].encode()).hexdigest()[:16] + ext)
        try:
            if not path.is_file():
                _download(item["url"], path)
        except ProviderError as e:
            last = e
            continue
        return {"path": str(path), "attribution": item["attribution"], "provider": "wikimedia", "media": "photo",
                "page": item.get("page")}
    raise last or ProviderError("bad_output", "Wikimedia: डाउनलोड नहीं हो सका।")


def _ai(query: str, variant: int, aspect: str, dest: Path, sleep=time.sleep) -> dict:
    w, h = AI_SIZE.get(aspect, (1280, 720))
    seed = int(hashlib.sha256(f"{query}|{variant}".encode()).hexdigest()[:6], 16)
    path = dest / f"ai_{hashlib.sha256(f'{query}|{variant}|{w}x{h}'.encode()).hexdigest()[:16]}.jpg"
    if not path.is_file():
        for attempt in range(1, AI_RETRIES + 1):
            gap = time.time() - _ai_last["t"]
            if gap < AI_PACE_S:
                sleep(AI_PACE_S - gap)
            try:
                res = pollinations_generate(query + AI_STYLE, {}, width=w, height=h, seed=seed)
                _ai_last["t"] = time.time()
                break
            except ProviderError as e:
                _ai_last["t"] = time.time()
                if e.kind not in ("rate_limited", "transient") or attempt == AI_RETRIES:
                    raise
                sleep(15.0 * attempt)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(res["bytes"])
        tmp.replace(path)
    return {"path": str(path), "attribution": "Image: Pollinations.ai (AI-generated)", "provider": "pollinations",
            "media": "photo", "page": None}


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def search_text(q: str) -> str:
    """Image search/generation works in English/Latin; Devanagari queries are transliterated first."""
    q = " ".join(q.split())
    return to_roman(q) if _DEVANAGARI.search(q) else q


def fetch_visual(kind: str, query: str, alt_queries: list[str], aspect: str, dest: Path, all_keys: dict,
                 notify: Callable[[str], None], variant: int = 0, stock_pref: str | None = None,
                 salt: str = "", sleep: Callable[[float], None] = time.sleep) -> dict | None:
    """Returns {"path", "attribution", "provider", "media"} or None (scene becomes avatar_only).
    salt (e.g. the scene id) makes scenes that share a query get different pictures."""
    if kind == "none" or not query.strip():
        return None
    query = search_text(query)
    alt_queries = [search_text(q) for q in alt_queries]
    if salt:
        variant += int(hashlib.sha256(salt.encode()).hexdigest()[:4], 16) % 97
    dest.mkdir(parents=True, exist_ok=True)
    stock_ok = bool(registry.chain("stock", None, all_keys))
    if kind in ("stock_video", "stock_image"):
        order = (["stock"] if stock_ok else []) + ["wiki", "ai"]
    elif kind == "wiki_image":
        order = ["wiki", "ai"]
    else:
        order = ["ai", "wiki"]
    errors = []
    for q in [query, *alt_queries][:3]:
        for src in order:
            try:
                if src == "stock":
                    return _stock(q, kind, variant, dest, all_keys, stock_pref, notify)
                if src == "wiki":
                    return _wiki(q, variant, dest)
                return _ai(q, variant, aspect, dest, sleep)
            except ProviderError as e:
                errors.append(f"{src}: {e}")
    notify(f"'{query[:40]}' के लिए कोई तस्वीर नहीं मिली — यह सीन सिर्फ़ अवतार के साथ बनेगा। ({'; '.join(errors)[:200]})")
    return None
