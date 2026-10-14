"""Workflow B API (PRD §9): catalog, wizard settings, research/facts, script, generate, per-scene regenerate,
YouTube pack, AI-disclosure gate, state."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import db, storage
from ..config import settings
from ..jobs import TERMINAL, runner
from ..providers.base import ProviderError
from ..providers.speech import edge_tts_synthesize
from ..security.keys import keys_from_request
from . import avatar as av
from . import llmjson, pack, pipeline
from .models import (ASPECTS, CAPTION_SCRIPTS, CAPTION_STYLES, LANGUAGES, LAYOUT_LABEL, RATES, VOICES,
                     ScriptError, manual_script, validate_facts, validate_script, validate_settings)

router = APIRouter(prefix="/api")
JOB_KINDS = ("research", "script", "generate", "regenerate", "pack")
PREVIEW_TEXT = "नमस्ते! मैं आपके वीडियो में इसी आवाज़ में बोलूँगा। आज हम कुछ नया और दिलचस्प सीखेंगे।"


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _project(pid: str) -> dict:
    p = pipeline.project(pid)
    if p is None:
        _err(404, "not_found", "प्रोजेक्ट नहीं मिला।")
    if p["kind"] != "create":
        _err(400, "wrong_kind", "यह 'टॉपिक से वीडियो' प्रोजेक्ट नहीं है।")
    return p


def _latest_job(pid: str, kind: str) -> dict | None:
    with db.locked() as c:
        row = c.execute("SELECT id FROM jobs WHERE project_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
                        (pid, kind)).fetchone()
    return runner.get(row["id"]) if row else None


def _ensure_idle(pid: str) -> None:
    for k in JOB_KINDS:
        j = _latest_job(pid, k)
        if j and j["status"] not in TERMINAL:
            _err(409, "busy", "इस प्रोजेक्ट में एक काम पहले से चल रहा है — पूरा होने दें या रोकें।")


# --- catalog ------------------------------------------------------------------------------------
@router.get("/create/catalog")
def catalog():
    return {**av.catalog(),
            "languages": [{"id": k, "label": v} for k, v in LANGUAGES.items()],
            "aspects": list(ASPECTS), "minutes": [1, 2, 3, 4, 5],
            "voices": [{"id": k, "label": v} for k, v in VOICES.items()],
            "rates": [{"id": k, "label": {"normal": "सामान्य", "slow": "धीमा", "fast": "तेज़"}[k]} for k in RATES],
            "layouts": [{"id": k, "label": v} for k, v in LAYOUT_LABEL.items()],
            "caption_styles": [{"id": k, "label": v} for k, v in CAPTION_STYLES.items()],
            "caption_scripts": [{"id": k, "label": v} for k, v in CAPTION_SCRIPTS.items()],
            "checklist": pack.HUMAN_VALUE_CHECKLIST}


@router.get("/create/catalog/file/{rel:path}")
def catalog_file(rel: str):
    p = av.asset_file(rel)
    if p is None:
        _err(404, "not_found", "फ़ाइल नहीं मिली।")
    return FileResponse(p, media_type="image/png" if p.suffix == ".png" else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/create/voice-preview")
async def voice_preview(voice: str = Query("hi-IN-SwaraNeural"), rate: str = Query("normal")):
    if voice not in VOICES or rate not in RATES:
        _err(400, "bad_voice", "यह आवाज़ उपलब्ध नहीं है।")
    d = settings.data_dir / "cache" / "voice_preview"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{hashlib.sha256(f'{voice}|{rate}|{PREVIEW_TEXT}'.encode()).hexdigest()[:12]}.mp3"
    if not out.is_file():
        try:
            await asyncio.to_thread(edge_tts_synthesize, PREVIEW_TEXT, {}, out, voice, RATES[rate])
        except ProviderError as e:
            out.unlink(missing_ok=True)
            _err(502, e.kind, str(e))
    return FileResponse(out, media_type="audio/mpeg")


# --- settings / facts / script ---------------------------------------------------------------------
class SettingsIn(BaseModel):
    wizard: dict


@router.put("/projects/{pid}/settings")
def put_settings(pid: str, body: SettingsIn):
    p = _project(pid)
    _ensure_idle(pid)
    s = validate_settings(body.wizard)
    if not s.topic:
        _err(400, "empty_topic", "टॉपिक लिखिए।")
    if s.music_asset_id:
        a = storage.get_asset(s.music_asset_id)
        if not a or a["project_id"] != pid or a["kind"] != "music":
            s.music_asset_id = None
    pipeline.update_settings(pid, wizard=s.model_dump())
    with db.locked() as c:
        c.execute("UPDATE projects SET title=?, updated_at=? WHERE id=?", (s.topic[:200], db.now(), pid))
    if p["status"] == "draft":
        storage.set_status(pid, "configured")
    return {"wizard": s.model_dump()}


@router.post("/projects/{pid}/research")
def start_research(pid: str, request: Request):
    _project(pid)
    _ensure_idle(pid)
    keys = keys_from_request(request)
    if not llmjson.has_llm(keys):
        _err(400, "no_llm", "Research के लिए AI key चाहिए (Settings → Groq/Gemini/OpenRouter)। चाहें तो research छोड़कर आगे बढ़ें।")
    return {"job_id": runner.submit("research", lambda ctx: pipeline.run_research(ctx, pid), keys=keys, project_id=pid)}


class FactsIn(BaseModel):
    facts: list


@router.put("/projects/{pid}/facts")
def put_facts(pid: str, body: FactsIn):
    _project(pid)
    _ensure_idle(pid)
    try:
        facts = validate_facts({"facts": body.facts}) if body.facts else []
    except ScriptError as e:
        _err(422, "facts_invalid", str(e))
    cur = pipeline.script_row(pid).get("facts") or {}
    pipeline.save_script_row(pid, facts={**cur, "facts": [f.model_dump() for f in facts], "edited_at": db.now()})
    storage.set_status(pid, "researched")
    return {"facts": [f.model_dump() for f in facts]}


class ScriptJobIn(BaseModel):
    fresh: bool = False


@router.post("/projects/{pid}/script")
def start_script(pid: str, body: ScriptJobIn, request: Request):
    _project(pid)
    _ensure_idle(pid)
    keys = keys_from_request(request)
    if not llmjson.has_llm(keys):
        _err(400, "no_llm", "स्क्रिप्ट AI से बनाने के लिए key चाहिए — या 'मैं ख़ुद लिखूँगा' चुनें।")
    return {"job_id": runner.submit("script", lambda ctx: pipeline.run_script(ctx, pid, body.fresh), keys=keys, project_id=pid)}


class ScriptIn(BaseModel):
    script: dict | None = None
    manual_text: str | None = None
    manual_keywords: str = ""


@router.put("/projects/{pid}/script")
def put_script(pid: str, body: ScriptIn):
    _project(pid)
    _ensure_idle(pid)
    s = pipeline.wizard(pid)
    try:
        if body.manual_text is not None:
            sc = manual_script(body.manual_text[:20000], s.topic, keywords=body.manual_keywords)
        elif body.script is not None:
            sc = validate_script(body.script, s.topic)
        else:
            _err(400, "empty", "स्क्रिप्ट नहीं भेजी गई।")
    except ScriptError as e:
        _err(422, "script_invalid", str(e))
    pipeline.save_script_row(pid, chapters={"script": sc.model_dump(), "complete": True, "sig": None})
    storage.set_status(pid, "scripted")
    return {"script": sc.model_dump()}


# --- generate / regenerate / pack ------------------------------------------------------------------
class GenerateIn(BaseModel):
    fresh: bool = False


@router.post("/projects/{pid}/generate")
def start_generate(pid: str, body: GenerateIn, request: Request):
    _project(pid)
    _ensure_idle(pid)
    if pipeline.script_of(pid) is None:
        _err(400, "no_script", "पहले स्क्रिप्ट बनाइए या लिखिए।")
    if body.fresh:
        pipeline.clear_cache(pid)
    keys = keys_from_request(request)
    return {"job_id": runner.submit("generate", lambda ctx: pipeline.generate(ctx, pid), keys=keys, project_id=pid)}


class RegenIn(BaseModel):
    what: str
    query: str | None = None
    text: str | None = None


@router.post("/projects/{pid}/scenes/{sid}/regenerate")
def regenerate_scene(pid: str, sid: str, body: RegenIn, request: Request):
    _project(pid)
    _ensure_idle(pid)
    if body.what not in ("visual", "voice", "text"):
        _err(400, "bad_what", "क्या बदलना है: visual, voice या text।")
    sc = pipeline.script_of(pid)
    if sc is None or not any(x.id == sid for ch in sc.chapters for x in ch.scenes):
        _err(404, "not_found", "यह सीन नहीं मिला।")
    keys = keys_from_request(request)
    return {"job_id": runner.submit("regenerate", lambda ctx: pipeline.regenerate(ctx, pid, sid, body.what, body.query, body.text),
                                    keys=keys, project_id=pid)}


@router.post("/projects/{pid}/youtube-pack")
def regen_pack(pid: str, request: Request):
    """Re-make titles/description/tags/platform texts (e.g. after adding an AI key). Video is reused."""
    _project(pid)
    _ensure_idle(pid)
    if not storage.list_assets(pid, ("output",)):
        _err(400, "no_video", "पहले वीडियो बनाइए।")
    keys = keys_from_request(request)

    def work(ctx):
        st = pipeline.load_state(pid)
        st.pop("meta", None)
        pipeline.save_state(pid, st)
        return pipeline.generate(ctx, pid)

    return {"job_id": runner.submit("pack", work, keys=keys, project_id=pid)}


class DisclosureIn(BaseModel):
    ack: bool
    checklist: list[bool] = []


@router.post("/projects/{pid}/disclosure")
def disclosure(pid: str, body: DisclosureIn):
    _project(pid)
    if body.ack and (len(body.checklist) < len(pack.HUMAN_VALUE_CHECKLIST) or not all(body.checklist)):
        _err(400, "checklist", "कृपया पहले सारे बिंदु पढ़कर टिक करें।")
    pipeline.update_settings(pid, disclosure_ack_at=db.now() if body.ack else None)
    return {"disclosure_ack_at": (pipeline.project(pid).get("settings") or {}).get("disclosure_ack_at")}


def disclosure_ok(project: dict) -> bool:
    return bool((project.get("settings") or {}).get("disclosure_ack_at"))


@router.get("/projects/{pid}/youtube-pack.txt")
def pack_text(pid: str, platform: str = Query("youtube")):
    p = _project(pid)
    if not disclosure_ok(p):
        _err(403, "disclosure_required", "डाउनलोड से पहले AI-disclosure की पुष्टि करें।")
    meta = pipeline.load_state(pid).get("meta")
    if not meta:
        _err(404, "no_pack", "पैक अभी नहीं बना।")
    if platform == "youtube":
        body = ("टाइटल विकल्प:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(meta["titles"]))
                + "\n\nविवरण:\n" + meta.get("youtube_description", meta["description"])
                + "\n\nटैग:\n" + ", ".join(meta["tags"]))
    else:
        pm = (meta.get("platforms") or {}).get(platform)
        if not pm:
            _err(404, "no_platform", "यह प्लेटफ़ॉर्म नहीं मिला।")
        body = f"{pm['title']}\n\n{pm['text']}\n\n{' '.join(pm['hashtags'])}"
    return PlainTextResponse(body, headers={"Content-Disposition": f'attachment; filename="{platform}-pack.txt"'})


# --- state + scene media ---------------------------------------------------------------------------
@router.get("/projects/{pid}/create-state")
def create_state(pid: str):
    p = _project(pid)
    row = pipeline.script_row(pid)
    facts = row.get("facts") or {}
    chapters = row.get("chapters") or {}
    st = pipeline.load_state(pid)
    script = (chapters.get("script") if chapters else None)
    scenes = {}
    last_layouts = (st.get("last") or {}).get("layouts") or {}
    for sid, e in (st.get("scenes") or {}).items():
        vis = e.get("visual") or {}
        scenes[sid] = {"duration": (e.get("voice") or {}).get("duration"),
                       "has_audio": bool((e.get("voice") or {}).get("path")),
                       "visual": ({"url": f"/api/projects/{pid}/scene-media/{sid}/visual", "attribution": vis.get("attribution"),
                                   "provider": vis.get("provider"), "media": vis.get("media")} if vis.get("path") else None),
                       "layout": last_layouts.get(sid) or (e.get("segment") or {}).get("layout")}
    pub = lambda kind: [storage.public_asset(a) for a in storage.list_assets(pid, (kind,))]  # noqa: E731
    meta = st.get("meta")
    return {
        "project": p, "wizard": pipeline.wizard(pid).model_dump(),
        "facts": facts.get("facts"), "sources": facts.get("sources") or [], "facts_provider": facts.get("provider"),
        "outline": row.get("outline"),
        "script": script, "script_complete": bool(chapters.get("complete", True)) if chapters else False,
        "scenes": scenes, "outputs": list(reversed(pub("output"))), "thumbnail": (pub("thumbnail") or [None])[-1],
        "music": pub("music"), "meta": meta, "notices": (st.get("last") or {}).get("notices") or [],
        "disclosure_ack_at": (p.get("settings") or {}).get("disclosure_ack_at"),
        "jobs": {k: _latest_job(pid, k) for k in JOB_KINDS},
        "checklist": pack.HUMAN_VALUE_CHECKLIST,
    }


@router.get("/projects/{pid}/scene-media/{sid}/{kind}")
def scene_media(pid: str, sid: str, kind: str):
    _project(pid)
    e = (pipeline.load_state(pid).get("scenes") or {}).get(sid) or {}
    path = (e.get("visual") or {}).get("path") if kind == "visual" else (e.get("voice") or {}).get("path") if kind == "audio" else None
    if not path:
        _err(404, "not_found", "फ़ाइल नहीं मिली।")
    p = Path(path).resolve()
    if settings.data_dir not in p.parents or not p.is_file():
        _err(404, "not_found", "फ़ाइल नहीं मिली।")
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
            ".mp4": "video/mp4", ".mp3": "audio/mpeg"}.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(p, media_type=mime)
