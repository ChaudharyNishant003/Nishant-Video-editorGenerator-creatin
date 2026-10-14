"""2D avatar renderer (PRD §11.4).

Character package = PNG layers + config.json (backend/app/assets/avatars/characters/<id>/).
Mouth movement is audio-driven and language-agnostic: RMS envelope of the narration (one window per
video frame, ≈42 ms at 24 fps) → smoothing → 4 mouth levels with hysteresis. Idle motion: blinks every
3–6 s and a 0–2 px breathing sway. Every visual state is pre-composited once, so producing a frame is a
lookup; frames are streamed as raw RGBA into ffmpeg's stdin by the job runner.
"""

from __future__ import annotations

import json
import math
import random
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageDraw

from ..render.ffmpeg import ffmpeg_exe

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "avatars"
CARD_CROP = (330, 140, 670, 640)   # head + chest, in character canvas pixels (for the corner card)
SWAY_PX = 2


# --- catalog -------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def characters() -> dict[str, dict]:
    out = {}
    for d in sorted((ASSETS / "characters").iterdir()):
        cfg = d / "config.json"
        if cfg.is_file():
            out[d.name] = {**json.loads(cfg.read_text(encoding="utf-8")), "dir": str(d)}
    return out


@lru_cache(maxsize=1)
def backgrounds() -> dict[str, dict]:
    meta = json.loads((ASSETS / "backgrounds" / "backgrounds.json").read_text(encoding="utf-8"))
    return meta


def background_path(bg_id: str, aspect: str) -> Path:
    bgs = backgrounds()
    meta = bgs.get(bg_id) or next(iter(bgs.values()))
    tag = {"16:9": "16x9", "9:16": "9x16", "1:1": "1x1"}.get(aspect, "16x9")
    return ASSETS / "backgrounds" / meta["files"][tag]


def catalog() -> dict:
    return {
        "characters": [{"id": cid, "label": c["label"], "description": c.get("description", ""),
                        "outfits": [{"id": o["id"], "label": o["label"], "color": o["color"]} for o in c["outfits"]],
                        "preview": f"characters/{cid}/preview.png"} for cid, c in characters().items()],
        "backgrounds": [{"id": bid, "label": b["label"], "preview": f"backgrounds/{b['preview']}"}
                        for bid, b in backgrounds().items()],
    }


def asset_file(rel: str) -> Path | None:
    """Resolve a catalog preview path safely (no traversal)."""
    p = (ASSETS / rel).resolve()
    return p if ASSETS in p.parents and p.is_file() and p.suffix in (".png", ".jpg") else None


# --- audio → mouth levels ----------------------------------------------------------------------------
def audio_envelope(audio: Path, fps: int, sr: int = 16000) -> np.ndarray:
    raw = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(audio), "-vn",
                          "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = sr / fps
    n = max(1, int(math.ceil(len(x) / hop)))
    env = np.zeros(n, np.float32)
    for i in range(n):
        seg = x[int(i * hop): int((i + 1) * hop)]
        if seg.size:
            env[i] = float(np.sqrt(np.mean(seg * seg)))
    return env


def mouth_levels(env: np.ndarray, n_frames: int) -> list[int]:
    """Quantise an RMS envelope into mouth levels 0..3 (0 = closed)."""
    if env.size == 0:
        return [0] * n_frames
    env = np.convolve(env, np.array([0.25, 0.5, 0.25], np.float32), mode="same")  # smooth
    voiced = env[env > 0.01]
    ref = float(np.percentile(voiced, 90)) if voiced.size else 1.0
    ref = max(ref, 1e-3)
    norm = env / ref
    up = (0.14, 0.38, 0.70)       # thresholds to open further
    down = (0.09, 0.30, 0.60)     # hysteresis: close a level only below these
    out, level = [], 0
    for i in range(n_frames):
        v = float(norm[i]) if i < norm.size else 0.0
        while level < 3 and v >= up[level]:
            level += 1
        while level > 0 and v < down[level - 1]:
            level -= 1
        out.append(level)
    return out


def blink_track(n_frames: int, fps: int, seed: int) -> list[bool]:
    rng = random.Random(seed)
    out = [False] * n_frames
    t = rng.uniform(1.0, 3.0)
    while True:
        f = int(t * fps)
        if f >= n_frames:
            break
        for k in range(f, min(n_frames, f + max(2, round(0.12 * fps)))):
            out[k] = True
        t += rng.uniform(3.0, 6.0)
    return out


def sway_track(n_frames: int, fps: int, phase: float = 0.0) -> list[int]:
    return [int(round((1 - math.cos(2 * math.pi * (i / fps) / 3.6 + phase)) / 2 * SWAY_PX)) for i in range(n_frames)]


# --- character states ----------------------------------------------------------------------------
def _rgba(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _tint(body: Image.Image, mask: Image.Image, color, base: float) -> Image.Image:
    a = np.asarray(body).astype(np.float32)
    m = (np.asarray(mask.convert("L")).astype(np.float32) / 255.0)[..., None]
    t = np.clip(a[..., :3] / base * np.array(color, np.float32), 0, 255)
    a[..., :3] = a[..., :3] * (1 - m) + t * m
    return Image.fromarray(a.astype("uint8"))


@dataclass
class AvatarSprites:
    """Pre-composited RGBA frames, indexed [eyes_closed][mouth_level][sway]."""
    width: int
    height: int
    states: list  # states[blink][level][sway] -> bytes

    def frames(self, levels: list[int], blinks: list[bool], sways: list[int]) -> Iterator[bytes]:
        for lv, bl, sw in zip(levels, blinks, sways):
            yield self.states[1 if bl else 0][lv][sw]


@lru_cache(maxsize=4)  # each entry is up to ~50 MB of raw frames
def build_sprites(char_id: str, outfit_id: str, mode: str, height: int, card_bg: str | None = None) -> AvatarSprites:
    """mode 'full' = seated figure on transparent background (chair static, person sways);
    mode 'card' = rounded picture-in-picture card (head + chest over a background)."""
    chars = characters()
    cfg = chars.get(char_id) or next(iter(chars.values()))
    d = Path(cfg["dir"])
    outfit = next((o for o in cfg["outfits"] if o["id"] == outfit_id), cfg["outfits"][0])
    body = _tint(_rgba(d / "body.png"), Image.open(d / cfg["outfit_mask"]), outfit["color"], cfg.get("outfit_base_gray", 200))
    chair = _rgba(d / "chair.png")
    front = _rgba(d / "front.png")
    closed = _rgba(d / cfg["eyes_closed"])
    mouths = [_rgba(d / m) for m in cfg["mouth_sprites"]]
    mx, my = cfg["mouth_anchor"]
    cw, ch = cfg["canvas"]

    if mode == "card":
        x0, y0, x1, y1 = CARD_CROP
        scale = height / (y1 - y0)
    else:
        x0, y0, x1, y1 = 0, 0, cw, ch
        scale = height / ch
    out_w = max(2, int(round((x1 - x0) * scale)) // 2 * 2)
    out_h = max(2, int(round(height)) // 2 * 2)

    def person(level: int, blink: bool) -> Image.Image:
        img = body.copy()
        if blink:
            img.alpha_composite(closed)
        m = mouths[level]
        img.alpha_composite(m, (int(mx - m.width / 2), int(my - m.height / 2)))
        img.alpha_composite(front)
        return img

    backdrop = None
    radius_mask = None
    if mode == "card":
        bg = Image.open(card_bg).convert("RGBA") if card_bg else Image.new("RGBA", (out_w, out_h), (40, 44, 70, 255))
        # cover-crop the background into the card
        s = max(out_w / bg.width, out_h / bg.height)
        bg = bg.resize((max(out_w, int(bg.width * s)), max(out_h, int(bg.height * s))), Image.LANCZOS)
        bx, by = (bg.width - out_w) // 2, (bg.height - out_h) // 2
        backdrop = bg.crop((bx, by, bx + out_w, by + out_h))
        radius_mask = Image.new("L", (out_w, out_h), 0)
        ImageDraw.Draw(radius_mask).rounded_rectangle((0, 0, out_w - 1, out_h - 1), radius=max(8, out_w // 10), fill=255)

    states: list = []
    for blink in (False, True):
        row = []
        for level in range(4):
            p = person(level, blink)
            sways = []
            for sw in range(SWAY_PX + 1):
                canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                if mode == "full":
                    canvas.alpha_composite(chair)
                canvas.alpha_composite(p, (0, sw * 2))  # canvas px → ~1–2 output px after scaling
                crop = canvas.crop((x0, y0, x1, y1)).resize((out_w, out_h), Image.BILINEAR)
                if mode == "card":
                    framed = backdrop.copy()
                    framed.alpha_composite(crop)
                    border = ImageDraw.Draw(framed)
                    border.rounded_rectangle((0, 0, out_w - 1, out_h - 1), radius=max(8, out_w // 10),
                                             outline=(255, 255, 255, 230), width=max(3, out_w // 60))
                    framed.putalpha(radius_mask)
                    crop = framed
                sways.append(crop.tobytes())
            row.append(sways)
        states.append(row)
    return AvatarSprites(out_w, out_h, states)


def frame_tracks(audio: Path, fps: int, n_frames: int, seed: int) -> tuple[list[int], list[bool], list[int]]:
    env = audio_envelope(audio, fps)
    return mouth_levels(env, n_frames), blink_track(n_frames, fps, seed), sway_track(n_frames, fps, seed % 7)


def head_crop(char_id: str, outfit_id: str, height: int) -> Image.Image:
    """Avatar head + chest (RGBA) for thumbnails."""
    sp = build_sprites(char_id, outfit_id, "card", height)
    return Image.frombytes("RGBA", (sp.width, sp.height), sp.states[0][0][0])
