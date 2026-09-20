"""
AI YT Studio — Phase 2 render backend.

A tiny local FastAPI service that adds the two things a browser can't do:
  1. /render/tts    — realistic, free Edge-TTS narration (returns an mp3)
  2. /render/video  — stitches scene images + per-scene Edge-TTS narration into
                      a real .mp4 with burned-in captions (via MoviePy/ffmpeg)

The Vite dev server proxies /render/* here (see vite.config.ts), so the frontend
calls it same-origin with no CORS setup needed.

Run:
    cd backend
    python -m venv .venv && .venv\\Scripts\\activate      (Windows)
    pip install -r requirements.txt
    uvicorn main:app --port 8000 --reload
"""

import asyncio
import base64
import io
import os
import tempfile
import textwrap

import edge_tts
import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

app = FastAPI(title="AI YT Studio render backend")

# The frontend reaches us via the Vite proxy (same-origin), but allow direct
# access from the dev origins too for convenience.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_VOICE = "en-US-AriaNeural"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class TtsIn(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    rate: str | None = None  # e.g. "+10%"


class SceneIn(BaseModel):
    scene: int
    narration: str = ""
    onScreenText: str = ""
    image: str | None = None  # remote URL or data: URI
    video: str | None = None  # (reserved) remote clip URL


class VideoJob(BaseModel):
    dimensions: str = "16:9"
    voice: str = DEFAULT_VOICE
    fps: int = 24
    scenes: list[SceneIn]


# --------------------------------------------------------------------------- #
# Edge-TTS helpers
# --------------------------------------------------------------------------- #
async def synth_to_file(text: str, voice: str, path: str, rate: str | None = None) -> None:
    kwargs = {}
    if rate:
        kwargs["rate"] = rate
    communicate = edge_tts.Communicate(text, voice or DEFAULT_VOICE, **kwargs)
    await communicate.save(path)


# --------------------------------------------------------------------------- #
# Image / frame building
# --------------------------------------------------------------------------- #
def _dims(ratio: str) -> tuple[int, int]:
    if ratio == "9:16":
        return 720, 1280
    if ratio == "1:1":
        return 1080, 1080
    return 1280, 720


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\ariblk.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        "DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fetch_image(spec: str) -> Image.Image:
    if spec.startswith("data:"):
        _, b64 = spec.split(",", 1)
        data = base64.b64decode(b64)
    else:
        resp = requests.get(spec, timeout=180)
        resp.raise_for_status()
        data = resp.content
    return Image.open(io.BytesIO(data)).convert("RGB")


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize + center-crop to fill w×h (object-fit: cover)."""
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = max(w, int(sw * scale)), max(h, int(sh * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _draw_caption(img: Image.Image, text: str, w: int, h: int) -> None:
    if not text.strip():
        return
    draw = ImageDraw.Draw(img, "RGBA")
    font = _load_font(max(24, int(h * 0.055)))
    wrapped = textwrap.fill(text.strip(), width=28)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=6)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (w - tw) // 2
    y = int(h * 0.80) - th // 2
    pad = int(h * 0.02)
    draw.rounded_rectangle(
        [x - pad, y - pad, x + tw + pad, y + th + pad],
        radius=pad,
        fill=(0, 0, 0, 140),
    )
    # simple stroke for legibility
    draw.multiline_text(
        (x, y), wrapped, font=font, fill=(255, 255, 255, 255),
        align="center", spacing=6, stroke_width=2, stroke_fill=(0, 0, 0, 255),
    )


def _build_frame(scene: SceneIn, w: int, h: int) -> np.ndarray:
    if scene.image:
        try:
            base = _cover(_fetch_image(scene.image), w, h)
        except Exception:
            base = Image.new("RGB", (w, h), (12, 14, 20))
    else:
        base = Image.new("RGB", (w, h), (12, 14, 20))
    _draw_caption(base, scene.onScreenText, w, h)
    return np.array(base)


# --------------------------------------------------------------------------- #
# Video assembly (runs in a worker thread — MoviePy/ffmpeg is blocking)
# --------------------------------------------------------------------------- #
def build_movie(prepared: list[tuple[SceneIn, str | None]], dimensions: str, fps: int, workdir: str) -> str:
    from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

    w, h = _dims(dimensions)
    clips = []
    for scene, audio_path in prepared:
        frame = _build_frame(scene, w, h)
        duration = 3.0
        audio = None
        if audio_path and os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            duration = max(1.0, audio.duration) + 0.35
        clip = ImageClip(frame).with_duration(duration)
        if audio is not None:
            clip = clip.with_audio(audio)
        clips.append(clip)

    if not clips:
        raise HTTPException(status_code=400, detail="No scenes to render.")

    final = concatenate_videoclips(clips, method="chain")
    out_path = os.path.join(workdir, "ai-yt-studio.mp4")
    final.write_videofile(
        out_path,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        logger=None,
        threads=4,
    )
    return out_path


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/render/health")
def health():
    return {"ok": True, "service": "ai-yt-studio-render", "voice_default": DEFAULT_VOICE}


@app.get("/render/voices")
async def voices(lang: str = "en"):
    """List Edge-TTS voices (optionally filtered by language prefix)."""
    all_voices = await edge_tts.list_voices()
    items = [
        {"name": v["ShortName"], "gender": v.get("Gender"), "locale": v.get("Locale")}
        for v in all_voices
        if not lang or v.get("Locale", "").lower().startswith(lang.lower())
    ]
    items.sort(key=lambda x: x["name"])
    return {"voices": items}


@app.post("/render/tts")
async def tts(body: TtsIn):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        await synth_to_file(body.text, body.voice, tmp.name, body.rate)
        with open(tmp.name, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return Response(content=data, media_type="audio/mpeg")


@app.post("/render/video")
async def render_video(job: VideoJob):
    if not job.scenes:
        raise HTTPException(status_code=400, detail="scenes are required")

    workdir = tempfile.mkdtemp(prefix="aiyt_")
    prepared: list[tuple[SceneIn, str | None]] = []

    # 1) Synthesize per-scene narration (sequential; Edge-TTS needs internet).
    for scene in job.scenes:
        audio_path = None
        if scene.narration.strip():
            audio_path = os.path.join(workdir, f"scene_{scene.scene}.mp3")
            try:
                await synth_to_file(scene.narration, job.voice, audio_path)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=502,
                    detail=f"Edge-TTS failed for scene {scene.scene}: {exc}. "
                    "Edge-TTS needs an internet connection.",
                )
        prepared.append((scene, audio_path))

    # 2) Assemble the mp4 in a worker thread.
    try:
        out_path = await asyncio.to_thread(build_movie, prepared, job.dimensions, job.fps, workdir)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Render failed: {exc}")

    return FileResponse(out_path, media_type="video/mp4", filename="ai-yt-studio.mp4")
