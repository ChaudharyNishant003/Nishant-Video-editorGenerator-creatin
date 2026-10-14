"""Workflow B data: wizard settings, facts, outline, chapter scripts (PRD §5.1, §5.3, §5.4).

Everything an LLM or the browser sends is untrusted: validators clamp, repair ids and fall back to
defaults instead of failing, and only raise ScriptError when nothing usable is left.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .avatar import backgrounds, characters
from .compose import LAYOUTS

LANGUAGES = {"hi": "हिंदी", "hinglish": "Hinglish (देवनागरी में)"}
ASPECTS = ("16:9", "9:16", "1:1")
LAYOUT_CHOICES = (*LAYOUTS, "auto")
LAYOUT_LABEL = {"avatar_center_side_inserts": "अवतार बीच में, साइड में तस्वीरें",
                "broll_fullscreen_avatar_corner": "पूरी स्क्रीन तस्वीर/क्लिप, अवतार कोने में",
                "avatar_only": "सिर्फ़ अवतार + कैप्शन", "auto": "Auto (AI हर सीन के लिए चुने)"}
CAPTION_STYLES = {"hindi_bold_word_highlight": "शब्द-दर-शब्द हाईलाइट", "line": "पूरी लाइन", "none": "कैप्शन नहीं"}
CAPTION_SCRIPTS = {"devanagari": "देवनागरी (डिफ़ॉल्ट)", "roman": "Roman Hinglish"}
VOICES = {"hi-IN-SwaraNeural": "स्वरा (महिला)", "hi-IN-MadhurNeural": "मधुर (पुरुष)"}
RATES = {"normal": None, "slow": "-8%", "fast": "+8%"}
VISUAL_KINDS = ("stock_image", "stock_video", "ai_image", "wiki_image", "none")


class ScriptError(ValueError):
    pass


def _clean(s: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


class WizardSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str = ""
    notes: str = ""
    audience: str = ""
    tone: str = ""
    language: str = "hi"
    aspect: str = "16:9"
    minutes: int = 3
    character: str = "aarav"
    outfit: str = "blue"
    background: str = "study"
    voice: str = "hi-IN-SwaraNeural"
    rate: str = "normal"
    layout: str = "auto"
    caption_style: str = "hindi_bold_word_highlight"
    caption_script: str = "devanagari"
    music_asset_id: str | None = None
    music_volume: float = 0.12


def validate_settings(raw: dict) -> WizardSettings:
    if not isinstance(raw, dict):
        raw = {}
    try:
        s = WizardSettings.model_validate(raw)
    except ValidationError:
        s = WizardSettings.model_validate({k: v for k, v in raw.items() if isinstance(v, (str, int, float))})
    s.topic = _clean(s.topic, 300)
    s.notes = str(s.notes or "").strip()[:4000]
    s.audience, s.tone = _clean(s.audience, 200), _clean(s.tone, 100)
    s.language = s.language if s.language in LANGUAGES else "hi"
    s.aspect = s.aspect if s.aspect in ASPECTS else "16:9"
    s.minutes = int(max(1, min(5, s.minutes)))
    chars = characters()
    if s.character not in chars:
        s.character = next(iter(chars))
    if s.outfit not in {o["id"] for o in chars[s.character]["outfits"]}:
        s.outfit = chars[s.character]["outfits"][0]["id"]
    if s.background not in backgrounds():
        s.background = next(iter(backgrounds()))
    s.voice = s.voice if s.voice in VOICES else "hi-IN-SwaraNeural"
    s.rate = s.rate if s.rate in RATES else "normal"
    s.layout = s.layout if s.layout in LAYOUT_CHOICES else "auto"
    s.caption_style = s.caption_style if s.caption_style in CAPTION_STYLES else "hindi_bold_word_highlight"
    s.caption_script = s.caption_script if s.caption_script in CAPTION_SCRIPTS else "devanagari"
    s.music_volume = round(max(0.0, min(1.0, float(s.music_volume))), 3)
    return s


# --- facts ---------------------------------------------------------------------------------------
class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    text: str
    source_url: str | None = None
    uncertain: bool = False


def validate_facts(raw: Any, allowed_sources: set[str] | None = None) -> list[Fact]:
    """allowed_sources: URLs actually fetched (+ 'notes'); a fact citing anything else is marked uncertain.
    None = trust the given sources (user edits)."""
    items = raw.get("facts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ScriptError("तथ्य सूची नहीं मिली।")
    out: list[Fact] = []
    for item in items[:60]:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        try:
            f = Fact.model_validate(item)
        except ValidationError:
            continue
        f.text = _clean(f.text, 500)
        if not f.text:
            continue
        src = (f.source_url or "").strip()[:500] or None
        if src and not (src == "notes" or src.startswith("https://") or src.startswith("http://")):
            src = None
        f.source_url = src
        if allowed_sources is not None and (src is None or src not in allowed_sources):
            f.uncertain = True
        out.append(f)
    for i, f in enumerate(out, 1):
        f.id = f"f{i}"
    return out


# --- outline + chapter scripts ---------------------------------------------------------------------
class OutlineChapter(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    summary: str = ""
    fact_refs: list[str] = []


class Outline(BaseModel):
    title: str = ""
    chapters: list[OutlineChapter]


class Visual(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str = "ai_image"
    query: str = ""
    alt_queries: list[str] = []


class Scene(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    text: str
    layout: str = "auto"
    visual: Visual = Field(default_factory=Visual)
    fact_refs: list[str] = []
    est_seconds: float | None = None


class Chapter(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chapter: int = 1
    title: str = ""
    scenes: list[Scene]


class Script(BaseModel):
    title: str = ""
    chapters: list[Chapter]
    manual: bool = False


def validate_outline(raw: Any, n_chapters: int) -> Outline:
    if not isinstance(raw, dict):
        raise ScriptError("Outline JSON object नहीं है।")
    chs = raw.get("chapters")
    if not isinstance(chs, list) or not chs:
        raise ScriptError("Outline में अध्याय नहीं हैं।")
    out = []
    for c in chs[: max(1, n_chapters + 1)]:
        if isinstance(c, str):
            c = {"title": c}
        if not isinstance(c, dict):
            continue
        try:
            oc = OutlineChapter.model_validate(c)
        except ValidationError:
            continue
        oc.title, oc.summary = _clean(oc.title, 120), _clean(oc.summary, 600)
        oc.fact_refs = [_clean(r, 10) for r in oc.fact_refs if isinstance(r, str)][:20]
        if oc.title:
            out.append(oc)
    if not out:
        raise ScriptError("Outline में कोई सही अध्याय नहीं।")
    return Outline(title=_clean(raw.get("title"), 150), chapters=out)


def _visual(v: Any, fallback_query: str) -> Visual:
    if isinstance(v, str):
        v = {"kind": "ai_image", "query": v}
    if not isinstance(v, dict):
        v = {}
    try:
        vis = Visual.model_validate(v)
    except ValidationError:
        vis = Visual()
    vis.kind = vis.kind if vis.kind in VISUAL_KINDS else "ai_image"
    vis.query = _clean(vis.query, 160) or fallback_query[:160]
    vis.alt_queries = [_clean(q, 160) for q in vis.alt_queries if isinstance(q, str) and q.strip()][:3]
    if vis.kind != "none" and not vis.query:
        vis.kind = "none"
    return vis


def validate_chapter(raw: Any, chapter_no: int, topic: str = "", fact_ids: set[str] | None = None) -> Chapter:
    if not isinstance(raw, dict):
        raise ScriptError("Chapter JSON object नहीं है।")
    scenes_in = raw.get("scenes")
    if not isinstance(scenes_in, list):
        narration = _clean(raw.get("narration"), 6000)
        if not narration:
            raise ScriptError("Chapter में scenes नहीं हैं।")
        scenes_in = [{"text": t} for t in split_sentences(narration)]
    scenes: list[Scene] = []
    for s in scenes_in[:40]:
        if isinstance(s, str):
            s = {"text": s}
        if not isinstance(s, dict) or not _clean(s.get("text"), 10):
            continue
        s = dict(s)
        s["visual"] = _visual(s.get("visual"), topic)
        try:
            sc = Scene.model_validate(s)
        except ValidationError:
            continue
        sc.text = _clean(sc.text, 700)
        sc.layout = sc.layout if sc.layout in LAYOUT_CHOICES else "auto"
        sc.fact_refs = [r for r in (str(x)[:10] for x in sc.fact_refs) if fact_ids is None or r in fact_ids][:10]
        if sc.est_seconds is not None:
            sc.est_seconds = max(1.0, min(120.0, float(sc.est_seconds)))
        scenes.append(sc)
    if not scenes:
        raise ScriptError("Chapter में कोई सही scene नहीं।")
    for i, sc in enumerate(scenes, 1):
        sc.id = f"c{chapter_no}s{i}"
    return Chapter(chapter=chapter_no, title=_clean(raw.get("title"), 120), scenes=scenes)


def validate_script(raw: Any, topic: str = "") -> Script:
    """User-edited script from the UI (PUT /script)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("chapters"), list):
        raise ScriptError("स्क्रिप्ट में अध्याय नहीं हैं।")
    chapters = []
    for c in raw["chapters"][:12]:
        try:
            chapters.append(validate_chapter(c, len(chapters) + 1, topic))
        except ScriptError:
            continue
    if not chapters:
        raise ScriptError("स्क्रिप्ट ख़ाली है — कम से कम एक वाक्य लिखें।")
    return Script(title=_clean(raw.get("title"), 150) or topic[:150], chapters=chapters, manual=bool(raw.get("manual")))


# --- manual script (no LLM key needed) -------------------------------------------------------------
_SENT = re.compile(r"(?<=[।?!॥.])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(re.sub(r"[ \t]+", " ", text or "")) if s.strip()]


def manual_script(text: str, topic: str, max_words: int = 26, keywords: str = "") -> Script:
    """Paragraphs → chapters (max 8); sentences grouped into scenes of ≤ max_words words.
    A first line starting with '#' becomes the chapter title. keywords (English, optional) drive the
    pictures; without them the topic is used (transliterated before any image search)."""
    visual_q = _clean(keywords, 160) or topic
    paras = [p.strip() for p in re.split(r"\n\s*\n", (text or "").replace("\r", "")) if p.strip()][:8]
    chapters = []
    for p in paras:
        lines = p.split("\n")
        title = ""
        if lines[0].lstrip().startswith("#"):
            title = lines[0].lstrip("# ").strip()
            lines = lines[1:]
        sents = split_sentences(" ".join(lines))
        scenes, cur = [], []
        for s in sents:
            if cur and len(" ".join(cur + [s]).split()) > max_words:
                scenes.append(" ".join(cur))
                cur = []
            cur.append(s)
        if cur:
            scenes.append(" ".join(cur))
        if not scenes:
            continue
        n = len(chapters) + 1
        chapters.append({"title": title or f"भाग {n}", "scenes": [
            {"text": t, "layout": "auto", "visual": {"kind": "ai_image", "query": visual_q}} for t in scenes]})
    return validate_script({"title": topic, "chapters": chapters, "manual": True}, topic)


def resolve_layouts(script: Script, wizard_layout: str) -> dict[str, str]:
    """Concrete layout per scene id. Fixed wizard choice wins; 'auto' keeps the LLM's pick, otherwise
    rotates so consecutive scenes don't look the same. Scenes without a visual become avatar_only."""
    rotation = ("avatar_center_side_inserts", "broll_fullscreen_avatar_corner", "avatar_center_side_inserts", "avatar_only")
    out, i = {}, 0
    for ch in script.chapters:
        for sc in ch.scenes:
            lay = wizard_layout if wizard_layout != "auto" else sc.layout
            if lay == "auto":
                lay = rotation[i % len(rotation)]
            if sc.visual.kind == "none" and lay != "avatar_only":
                lay = "avatar_only"
            out[sc.id] = lay
            i += 1
    return out
