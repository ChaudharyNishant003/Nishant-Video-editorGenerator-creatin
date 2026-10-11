"""AI YT Studio v2 API (PRD §9). Run: python -m uvicorn app.main:app --app-dir backend --port 8001"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import auth, db, storage
from .config import settings
from .edit import routes as edit_routes
from .jobs import TERMINAL, runner
from .providers import registry
from .providers.base import ProviderError
from .security import redact
from .security.keys import keys_from_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
redact.install()
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app):
    db.conn()
    runner.recover_after_restart()
    if not settings.app_password or not settings.session_secret:
        log.warning("APP_PASSWORD / SESSION_SECRET not set — login will fail until backend/.env is configured.")
    yield


app = FastAPI(title="AI YT Studio v2", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(edit_routes.router)

PUBLIC_API = ("/api/auth/", "/api/health")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'none'; form-action 'self'")


@app.middleware("http")
async def gate_and_headers(request: Request, call_next):
    path = request.url.path
    needs_auth = (path.startswith("/api/") and not path.startswith(PUBLIC_API)) or path.startswith("/media/")
    if needs_auth and not auth.is_authenticated(request):
        resp = JSONResponse({"error": {"code": "unauthenticated", "message": "कृपया पहले लॉग-इन करें।"}}, status_code=401)
    else:
        resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    if path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse({"error": detail}, status_code=exc.status_code)


@app.exception_handler(ProviderError)
async def provider_error(request: Request, exc: ProviderError):
    return JSONResponse({"error": {"code": exc.kind, "message": redact.redact(str(exc))}}, status_code=502)


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


@app.get("/api/health")
def health():
    return {"ok": True, "service": "ai-yt-studio-v2"}


# --- providers ----------------------------------------------------------------
@app.get("/api/providers")
def providers():
    return {"capabilities": registry.metadata()}


@app.post("/api/providers/{provider_id}/test")
def test_provider(provider_id: str, request: Request):
    keys = keys_from_request(request)
    try:
        p = registry.get(provider_id)
    except ProviderError:
        _err(404, "unknown_provider", "यह provider मौजूद नहीं है।")
    result = p.health_check(p.keys_for(keys))
    return {"provider": provider_id, "checked_at": round(time.time()), **result}


# --- preferences (non-secret only) ---------------------------------------------
SECRET_HINTS = ("key", "token", "secret", "password")


class PrefsIn(BaseModel):
    values: dict[str, str]


@app.get("/api/preferences")
def get_prefs():
    with db.locked() as c:
        rows = c.execute("SELECT key, value FROM preferences").fetchall()
    return {"values": {r["key"]: r["value"] for r in rows}}


@app.put("/api/preferences")
def put_prefs(body: PrefsIn):
    for k in body.values:
        if any(h in k.lower() for h in SECRET_HINTS):
            _err(400, "secret_in_preferences", "Keys/secret preferences में सहेजे नहीं जा सकते।")
    with db.locked() as c:
        for k, v in body.values.items():
            c.execute("INSERT OR REPLACE INTO preferences(key, value) VALUES (?,?)", (k[:100], v[:2000]))
    return get_prefs()


# --- projects -----------------------------------------------------------------
class ProjectIn(BaseModel):
    kind: str
    title: str = ""


@app.get("/api/projects")
def list_projects():
    with db.locked() as c:
        rows = c.execute("SELECT * FROM projects ORDER BY updated_at DESC LIMIT 50").fetchall()
    return {"projects": [db.row_to_dict(r) for r in rows]}


@app.post("/api/projects")
def create_project(body: ProjectIn):
    if body.kind not in ("edit", "create"):
        _err(400, "bad_kind", "kind 'edit' या 'create' होना चाहिए।")
    pid, ts = db.new_id(), db.now()
    title = body.title.strip()[:200] or ("मेरा एडिट" if body.kind == "edit" else "नया वीडियो")
    with db.locked() as c:
        c.execute("INSERT INTO projects(id, kind, title, status, created_at, updated_at, settings_json) VALUES (?,?,?,?,?,?,?)",
                  (pid, body.kind, title, "draft", ts, ts, "{}"))
    return get_project(pid)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    with db.locked() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        _err(404, "not_found", "प्रोजेक्ट नहीं मिला।")
    return db.row_to_dict(row)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    get_project(project_id)
    with db.locked() as c:
        active = [r["id"] for r in c.execute("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')",
                                             (project_id,)).fetchall()]
    for job_id in active:
        runner.cancel(job_id)
    with db.locked() as c:
        for table in ("assets", "transcripts", "edit_plans", "scripts", "jobs"):
            c.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))
    storage.remove_project_dir(project_id)  # media of this v2 project only (DATA_DIR/projects/<id>)
    return {"ok": True}


# --- jobs ---------------------------------------------------------------------
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = runner.get(job_id)
    if job is None:
        _err(404, "not_found", "Job नहीं मिला।")
    return job


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    get_job(job_id)

    async def stream():
        last = None
        while True:
            job = runner.get(job_id)
            payload = json.dumps(job, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if job["status"] in TERMINAL:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    get_job(job_id)
    return {"cancelled": runner.cancel(job_id)}


class SelfTestIn(BaseModel):
    seconds: float = 20.0


@app.post("/api/jobs/selftest")
def selftest_job(body: SelfTestIn, request: Request):
    """Diagnostics: an ffmpeg job (synthetic video to null) to exercise progress + cancel.
    Accepts provider keys like a real job so key-handling can be tested end to end."""
    keys = keys_from_request(request)
    seconds = max(1.0, min(body.seconds, 600.0))

    def work(ctx):
        ctx.log(f"Selftest शुरू: {seconds:.0f}s की synthetic render ({len(ctx.keys)} provider keys memory में)।")
        ctx.run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=24:duration={seconds}",
                        "-c:v", "libx264", "-preset", "veryfast", "-f", "null", "-"],
                       expected_duration_s=seconds, step="selftest")
        ctx.log("Selftest पूरा।")
        return {"seconds": seconds}

    return {"job_id": runner.submit("selftest", work, keys=keys)}


# --- frontend (production: serve the built SPA) ----------------------------------
@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    dist = settings.frontend_dist
    if full_path.startswith("api/"):
        _err(404, "not_found", "Endpoint नहीं मिला।")
    target = (dist / full_path).resolve()
    if full_path and target.is_file() and dist in target.parents:
        return FileResponse(target)
    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"error": {"code": "frontend_not_built",
                                   "message": "Frontend build नहीं मिला — dev में http://localhost:5174 खोलें।"}}, status_code=404)
