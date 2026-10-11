"""Workflow A API (PRD §9): upload, transcribe, plan, approve-and-render, assets."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db, storage
from ..config import settings
from ..jobs import TERMINAL, runner
from ..render.probe import probe
from ..security.keys import keys_from_request
from . import pipeline, planner
from .captions import group_words
from .plan import PlanError, validate_plan

router = APIRouter(prefix="/api")

UPLOAD_EXT = {
    "source": {".mp4", ".mov", ".webm", ".m4v", ".mkv"},
    "music": {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"},
    "broll": {".mp4", ".mov", ".webm", ".m4v", ".jpg", ".jpeg", ".png", ".webp"},
}
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".flac": "audio/flac", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _project(pid: str) -> dict:
    with db.locked() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None:
        _err(404, "not_found", "प्रोजेक्ट नहीं मिला।")
    p = db.row_to_dict(row)
    if p["kind"] != "edit":
        _err(400, "wrong_kind", "यह 'वीडियो एडिट' प्रोजेक्ट नहीं है।")
    return p


def _latest_job(pid: str, kind: str) -> dict | None:
    with db.locked() as c:
        row = c.execute("SELECT id FROM jobs WHERE project_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
                        (pid, kind)).fetchone()
    return runner.get(row["id"]) if row else None


def _busy(pid: str, kinds: tuple[str, ...]) -> bool:
    return any((j := _latest_job(pid, k)) and j["status"] not in TERMINAL for k in kinds)


def _latest_plan_row(pid: str) -> dict | None:
    with db.locked() as c:
        row = c.execute("SELECT * FROM edit_plans WHERE project_id=? ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    return db.row_to_dict(row)


def _save_plan(pid: str, plan, prompt: str | None) -> dict:
    with db.locked() as c:
        v = (c.execute("SELECT MAX(version) AS v FROM edit_plans WHERE project_id=?", (pid,)).fetchone()["v"] or 0) + 1
        c.execute("INSERT INTO edit_plans(id, project_id, version, prompt, plan_json, approved_at, created_at) VALUES (?,?,?,?,?,?,?)",
                  (db.new_id(), pid, v, prompt, plan.model_dump_json(), None, db.now()))
    storage.set_status(pid, "planned")
    return _latest_plan_row(pid)


def _upload_ids(pid: str) -> set[str]:
    return {a["id"] for a in storage.list_assets(pid, ("music", "broll"))}


def _work_duration(pid: str) -> float:
    work = storage.latest_asset(pid, "work")
    if work is None:
        _err(409, "not_ingested", "वीडियो अभी तैयार नहीं हुआ (ingest बाकी है)।")
    return float(work["duration_s"])


# --- upload ------------------------------------------------------------------------------------
@router.post("/projects/{pid}/upload")
async def upload(pid: str, request: Request, kind: str = Query("source"), name: str = Query("video.mp4"),
                 language: str = Query("hi")):
    project = await run_in_threadpool(_project, pid)
    if kind not in UPLOAD_EXT:
        _err(400, "bad_kind", "अज्ञात upload प्रकार।")
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_EXT[kind]:
        _err(400, "bad_type", f"यह फ़ाइल प्रकार नहीं चलेगा ({ext or '?'}). चलेंगे: {', '.join(sorted(UPLOAD_EXT[kind]))}")
    if kind == "source" and storage.list_assets(pid, ("source",)):
        _err(409, "source_exists", "इस प्रोजेक्ट में पहले से वीडियो है — नया वीडियो नए प्रोजेक्ट में डालें।")
    limit = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        _err(413, "too_large", f"फ़ाइल {settings.max_upload_mb} MB से बड़ी है।")

    d = storage.project_dir(pid)
    target = d / ("source" + ext) if kind == "source" else d / "uploads" / (db.new_id() + ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(ext + ".part")
    size = 0
    try:
        with open(part, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, {"code": "too_large", "message": f"फ़ाइल {settings.max_upload_mb} MB से बड़ी है।"})
                f.write(chunk)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if size == 0:
        part.unlink(missing_ok=True)
        _err(400, "empty", "फ़ाइल ख़ाली है या upload अधूरा रहा — फिर कोशिश करें।")
    part.replace(target)

    try:
        info = await run_in_threadpool(probe, target)
    except ValueError:
        info = None
    reason = None
    if info is None:
        reason = "फ़ाइल पढ़ी नहीं जा सकी — क्या यह सही video/audio है?"
    elif kind == "source":
        if not info["has_video"] or info["is_image"]:
            reason = "इस फ़ाइल में video stream नहीं है।"
        elif not info["duration"]:
            reason = "वीडियो की लंबाई पता नहीं चली।"
        elif info["duration"] > settings.max_upload_seconds + 0.5:
            reason = f"वीडियो {info['duration']:.0f} s का है — सीमा {settings.max_upload_seconds} s है।"
        elif not info["width"] or not info["height"]:
            reason = "वीडियो का आकार पता नहीं चला।"
    elif kind == "music" and not info["has_audio"]:
        reason = "इस फ़ाइल में audio नहीं है।"
    elif kind == "broll" and not info["has_video"]:
        reason = "इस फ़ाइल में video/image नहीं है।"
    if reason:
        target.unlink(missing_ok=True)
        _err(400, "invalid_media", reason)

    asset = storage.add_asset(pid, kind, target, MIME.get(ext), info["duration"] if not info["is_image"] else None,
                              {"name": Path(name).name[:120], "size": size, "probe": info})
    out = {"asset": storage.public_asset(asset)}
    if kind == "source":
        lang = language if language in ("hi", "en") else "hi"
        with db.locked() as c:
            c.execute("UPDATE projects SET settings_json=?, status='uploaded', updated_at=? WHERE id=?",
                      (json.dumps({**(project.get("settings") or {}), "language": lang}), db.now(), pid))
        out["job_id"] = runner.submit("ingest", lambda ctx: pipeline.ingest(ctx, pid, asset), project_id=pid)
    return out


# --- transcribe ----------------------------------------------------------------------------------
class TranscribeIn(BaseModel):
    language: str | None = None


@router.post("/projects/{pid}/transcribe")
def transcribe(pid: str, body: TranscribeIn, request: Request):
    project = _project(pid)
    _work_duration(pid)
    if _busy(pid, ("ingest", "transcribe")):
        _err(409, "busy", "एक job पहले से चल रहा है।")
    lang = body.language or (project.get("settings") or {}).get("language") or "hi"
    if lang not in ("hi", "en"):
        lang = "hi"
    keys = keys_from_request(request)
    return {"job_id": runner.submit("transcribe", lambda ctx: pipeline.transcribe(ctx, pid, lang), keys=keys, project_id=pid)}


# --- plan ----------------------------------------------------------------------------------------
class PromptIn(BaseModel):
    prompt: str


class PlanIn(BaseModel):
    plan: dict
    prompt: str | None = None


@router.post("/projects/{pid}/plan")
def make_plan(pid: str, body: PromptIn, request: Request):
    _project(pid)
    D = _work_duration(pid)
    if not body.prompt.strip():
        _err(400, "empty_prompt", "बताइए क्या बदलना है।")
    tr = pipeline.latest_transcript(pid)
    assets = [storage.public_asset(a) for a in storage.list_assets(pid, ("music", "broll"))]
    notices: list[str] = []
    keys = keys_from_request(request)
    try:
        plan, provider = planner.make_plan(body.prompt, D, (tr or {}).get("words"), assets, keys,
                                           pipeline.get_pref("default.llm"), notices.append)
    except PlanError as e:
        _err(422, "plan_invalid", str(e))
    finally:
        keys.clear()
    row = _save_plan(pid, plan, body.prompt.strip()[:4000])
    return {"plan": _plan_out(pid, row), "notices": notices, "provider": provider}


@router.put("/projects/{pid}/plan")
def save_plan(pid: str, body: PlanIn):
    _project(pid)
    D = _work_duration(pid)
    try:
        plan = validate_plan(body.plan, D, _upload_ids(pid))
    except PlanError as e:
        _err(422, "plan_invalid", str(e))
    prev = _latest_plan_row(pid)
    prompt = body.prompt if body.prompt is not None else (prev or {}).get("prompt")
    return {"plan": _plan_out(pid, _save_plan(pid, plan, prompt))}


def _plan_out(pid: str, row: dict | None) -> dict | None:
    if row is None:
        return None
    from .plan import Plan

    plan = Plan.model_validate(row["plan"])
    tm = pipeline.timemap_for(pid, plan)
    return {"version": row["version"], "prompt": row["prompt"], "plan": row["plan"], "approved_at": row["approved_at"],
            "created_at": row["created_at"], "expected_duration_s": round(tm.total, 2) if tm else None}


@router.post("/projects/{pid}/approve-and-render")
def approve_and_render(pid: str, request: Request):
    _project(pid)
    D = _work_duration(pid)
    row = _latest_plan_row(pid)
    if row is None:
        _err(400, "no_plan", "पहले प्लान बनाइए या सहेजिए।")
    if _busy(pid, ("ingest", "render")):
        _err(409, "busy", "एक रेंडर पहले से चल रहा है।")
    try:
        plan = validate_plan(row["plan"], D, _upload_ids(pid))
    except PlanError as e:
        _err(422, "plan_invalid", str(e))
    if not plan.ops:
        _err(400, "empty_plan", "प्लान में कोई बदलाव नहीं है।")
    with db.locked() as c:
        c.execute("UPDATE edit_plans SET approved_at=? WHERE project_id=? AND version=?", (db.now(), pid, row["version"]))
    keys = keys_from_request(request)
    version = row["version"]
    return {"job_id": runner.submit("render", lambda ctx: pipeline.render(ctx, pid, plan, version), keys=keys, project_id=pid)}


# --- state + assets ------------------------------------------------------------------------------
@router.get("/projects/{pid}/state")
def state(pid: str):
    project = _project(pid)
    assets = storage.list_assets(pid)
    pub = lambda kind: [storage.public_asset(a) for a in assets if a["kind"] == kind]  # noqa: E731
    tr = pipeline.latest_transcript(pid)
    transcript = None
    if tr is not None:
        words = tr.get("words") or []
        transcript = {"provider": tr["provider"], "language": tr["language"], "word_count": len(words), "words": words,
                      "created_at": tr["created_at"],
                      "segments": [{"start": g[0]["start"], "end": g[-1]["end"], "text": " ".join(w["text"] for w in g)}
                                   for g in group_words(words, 14, max_gap=0.8, max_span=8.0)]}
    return {
        "project": project,
        "source": (pub("source") or [None])[-1],
        "work": (pub("work") or [None])[-1],
        "uploads": pub("music") + pub("broll"),
        "outputs": list(reversed(pub("output"))),
        "transcript": transcript,
        "plan": _plan_out(pid, _latest_plan_row(pid)),
        "jobs": {k: _latest_job(pid, k) for k in ("ingest", "transcribe", "render")},
        "limits": {"max_upload_mb": settings.max_upload_mb, "max_upload_seconds": settings.max_upload_seconds},
    }


@router.get("/assets/{aid}")
def get_asset(aid: str, download: int = 0):
    a = storage.get_asset(aid)
    if a is None:
        _err(404, "not_found", "फ़ाइल नहीं मिली।")
    path = Path(a["path"]).resolve()
    if settings.data_dir not in path.parents or not path.is_file():
        _err(404, "not_found", "फ़ाइल नहीं मिली।")
    name = (a.get("meta") or {}).get("name") or path.name
    if download:
        return FileResponse(path, media_type=a.get("mime") or "application/octet-stream", filename=name)
    return FileResponse(path, media_type=a.get("mime") or "application/octet-stream")
