"""Brand kit API (handoff §6 extras): logo watermark, accent colour, intro/outro clips."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import brand, db, storage
from .config import settings
from .create.compose import hex_to_bgr
from .render.probe import probe

router = APIRouter(prefix="/api/brand")
MAX_CLIP_S = 30.0
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".mp4": "video/mp4",
        ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/mp4", ".mkv": "video/x-matroska"}


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


@router.get("")
def get_brand():
    return brand.state()


class BrandIn(BaseModel):
    position: str | None = None
    opacity: float | None = None
    scale: float | None = None
    accent: str | None = None
    apply_edit: bool | None = None
    apply_create: bool | None = None
    intro: bool | None = None
    outro: bool | None = None


@router.put("")
def put_brand(body: BrandIn):
    vals: dict[str, str] = {}
    if body.position is not None:
        if body.position not in brand.POSITIONS:
            _err(400, "bad_position", "लोगो की जगह सही नहीं।")
        vals["brand.position"] = body.position
    if body.opacity is not None:
        vals["brand.opacity"] = f"{max(0.1, min(1.0, body.opacity)):.2f}"
    if body.scale is not None:
        vals["brand.scale"] = f"{max(0.04, min(0.3, body.scale)):.3f}"
    if body.accent is not None:
        if body.accent and not hex_to_bgr(body.accent):
            _err(400, "bad_color", "रंग #RRGGBB रूप में दें।")
        vals["brand.accent"] = body.accent
    for k in ("apply_edit", "apply_create", "intro", "outro"):
        v = getattr(body, k)
        if v is not None:
            vals[f"brand.{k}"] = "1" if v else "0"
    with db.locked() as c:
        for k, v in vals.items():
            c.execute("INSERT OR REPLACE INTO preferences(key, value) VALUES (?,?)", (k, v))
    return brand.state()


@router.post("/upload")
async def upload(request: Request, kind: str = Query(...), name: str = Query("file")):
    if kind not in brand.KINDS:
        _err(400, "bad_kind", "अज्ञात फ़ाइल प्रकार (logo/intro/outro)।")
    ext = Path(name).suffix.lower()
    if ext not in brand.KINDS[kind]:
        _err(400, "bad_type", f"यह फ़ाइल प्रकार नहीं चलेगा ({ext or '?'}). चलेंगे: {', '.join(sorted(brand.KINDS[kind]))}")
    limit = (10 if kind == "logo" else 150) * 1024 * 1024
    staging = brand.brand_dir() / f"upload_{kind}{ext}"
    try:
        await storage.stream_to(request, staging, limit)
    except ValueError as e:
        _err(413 if str(e) == "too_large" else 400, str(e), "फ़ाइल बहुत बड़ी है।" if str(e) == "too_large"
             else "फ़ाइल ख़ाली है या upload अधूरा रहा।")
    try:
        info = await run_in_threadpool(probe, staging)
    except ValueError:
        info = None
    reason = None
    if not info or not info["has_video"]:
        reason = "फ़ाइल पढ़ी नहीं जा सकी।"
    elif kind == "logo" and not info["is_image"] and ext not in (".png", ".jpg", ".jpeg", ".webp"):
        reason = "लोगो एक image होनी चाहिए।"
    elif kind != "logo" and (info["is_image"] or not info["duration"]):
        reason = "Intro/outro एक वीडियो होना चाहिए।"
    elif kind != "logo" and info["duration"] > MAX_CLIP_S + 0.5:
        reason = f"Intro/outro {MAX_CLIP_S:.0f} सेकंड से छोटा होना चाहिए।"
    if reason:
        staging.unlink(missing_ok=True)
        _err(400, "invalid_media", reason)
    for old in brand.brand_dir().glob(f"{kind}.*"):
        old.unlink(missing_ok=True)
    staging.replace(brand.brand_dir() / f"{kind}{ext}")
    return brand.state()


@router.delete("/{kind}")
def delete_file(kind: str):
    if kind not in brand.KINDS:
        _err(400, "bad_kind", "अज्ञात फ़ाइल प्रकार।")
    for old in brand.brand_dir().glob(f"{kind}.*"):
        old.unlink(missing_ok=True)
    return brand.state()


@router.get("/file/{kind}")
def get_file(kind: str):
    if kind not in brand.KINDS:
        _err(400, "bad_kind", "अज्ञात फ़ाइल प्रकार।")
    f = brand.file_for(kind)
    if f is None or settings.data_dir not in f.resolve().parents:
        _err(404, "not_found", "फ़ाइल नहीं मिली।")
    return FileResponse(f, media_type=MIME.get(f.suffix.lower(), "application/octet-stream"))
