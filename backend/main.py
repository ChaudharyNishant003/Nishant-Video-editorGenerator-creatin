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
    video: str | None = None  # generated clip: remote URL or data: URI


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


def _caption_overlay(text: str, w: int, h: int) -> Image.Image | None:
    """A transparent RGBA layer holding just the caption, so it can be composited
    on top of a moving (Ken-Burns or video) background without moving itself."""
    if not text.strip():
        return None
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
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
    return overlay


def _build_frame(scene: SceneIn, w: int, h: int) -> np.ndarray:
    """The scene's background only (no caption — that's composited separately
    so it stays fixed while the background pans/zooms)."""
    if scene.image:
        try:
            base = _cover(_fetch_image(scene.image), w, h)
        except Exception:
            base = Image.new("RGB", (w, h), (12, 14, 20))
    else:
        base = Image.new("RGB", (w, h), (12, 14, 20))
    return np.array(base)


def _fetch_video_to_file(spec: str, workdir: str, idx: int) -> str:
    """Download a scene's generated clip (remote URL or data: URI) to a local file
    — VideoFileClip needs a real path, it can't read from bytes in memory."""
    if spec.startswith("data:"):
        _, b64 = spec.split(",", 1)
        data = base64.b64decode(b64)
    else:
        resp = requests.get(spec, timeout=180)
        resp.raise_for_status()
        data = resp.content
    path = os.path.join(workdir, f"scene_{idx}_clip.mp4")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _cover_resize_video(clip, w: int, h: int):
    """Scale a video clip to cover (w, h) then center-crop — same idea as _cover()
    for stills, so a clip of any aspect ratio fills the target frame with no bars."""
    scale = max(w / clip.w, h / clip.h)
    resized = clip.resized(scale)
    return resized.cropped(x_center=resized.w / 2, y_center=resized.h / 2, width=w, height=h)


def _fit_video_duration(clip, target: float):
    """Loop a clip that's shorter than the narration, or trim one that's longer,
    so every scene's visual lasts exactly as long as its audio."""
    from moviepy.video.fx import Loop

    if clip.duration < target:
        clip = clip.with_effects([Loop(duration=target)])
    return clip.subclipped(0, target)


def _ken_burns_clip(frame: np.ndarray, w: int, h: int, duration: float, zoom_in: bool):
    """A slow zoom in (or out) on a still image — the classic Ken-Burns effect —
    used for any scene that has no generated video clip.

    Builds the frame directly (resize + center-crop, one PIL call per output frame)
    instead of moviepy's generic Resize-effect + CompositeVideoClip path: that
    combination was the single biggest render-time cost in testing (LANCZOS
    resampling on every frame, plus a compositing layer that wasn't needed for a
    single opaque clip). BILINEAR is a much cheaper resample and is indistinguishable
    from LANCZOS at the subtle ~12% zoom used here.
    """
    from moviepy import VideoClip

    src = Image.fromarray(frame)  # already exactly (w, h)
    start, end = (1.0, 1.12) if zoom_in else (1.12, 1.0)

    def make_frame(t: float) -> np.ndarray:
        p = min(max(t / duration, 0.0), 1.0) if duration > 0 else 0.0
        scale = start + (end - start) * p
        nw, nh = max(w, round(w * scale)), max(h, round(h * scale))
        resized = src.resize((nw, nh), Image.Resampling.BILINEAR)
        left, top = (nw - w) // 2, (nh - h) // 2
        return np.array(resized.crop((left, top, left + w, top + h)))

    return VideoClip(make_frame, duration=duration)


# --------------------------------------------------------------------------- #
# Video assembly (runs in a worker thread — MoviePy/ffmpeg is blocking)
# --------------------------------------------------------------------------- #
def build_movie(prepared: list[tuple[SceneIn, str | None]], dimensions: str, fps: int, workdir: str) -> str:
    from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips

    w, h = _dims(dimensions)
    clips = []
    for i, (scene, audio_path) in enumerate(prepared):
        duration = 3.0
        audio = None
        if audio_path and os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            duration = max(1.0, audio.duration) + 0.35

        visual = None
        if scene.video:
            try:
                clip_path = _fetch_video_to_file(scene.video, workdir, i)
                vclip = _cover_resize_video(VideoFileClip(clip_path), w, h)
                visual = _fit_video_duration(vclip, duration) if audio is not None else vclip
                if audio is None:
                    duration = visual.duration
            except Exception:
                # Clip couldn't be fetched/decoded — fall back to the still below
                # rather than failing the whole render.
                visual = None

        if visual is None:
            frame = _build_frame(scene, w, h)
            visual = _ken_burns_clip(frame, w, h, duration, zoom_in=(i % 2 == 0))

        caption = _caption_overlay(scene.onScreenText, w, h)
        if caption is not None:
            cap_clip = ImageClip(np.array(caption)).with_duration(visual.duration)
            visual = CompositeVideoClip([visual, cap_clip], size=(w, h))

        if audio is not None:
            visual = visual.with_audio(audio)
        clips.append(visual)

    if not clips:
        raise HTTPException(status_code=400, detail="No scenes to render.")

    final = concatenate_videoclips(clips, method="chain")
    out_path = os.path.join(workdir, "ai-yt-studio.mp4")
    temp_audio_path = os.path.join(workdir, "temp_audio.m4a")
    # Windows (often antivirus real-time scanning) can transiently lock MoviePy's
    # temp audio file right as it tries to reopen it for muxing (WinError 32) —
    # a known MoviePy/Windows issue. Pointing it at our own unique workdir avoids
    # most collisions; a single retry clears the rest (it's a timing fluke, not
    # a real failure — succeeds on the second attempt in practice).
    for attempt in range(2):
        try:
            final.write_videofile(
                out_path,
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=temp_audio_path,
                remove_temp=True,
                logger=None,
                threads=4,
            )
            break
        except (OSError, PermissionError):
            if attempt == 1:
                raise
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
