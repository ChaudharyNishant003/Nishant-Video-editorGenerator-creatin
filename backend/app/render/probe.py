"""Media probing. Uses ffprobe when available (Docker image), otherwise parses `ffmpeg -i`
(the bundled imageio-ffmpeg binary ships without ffprobe)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .ffmpeg import ffmpeg_exe


@lru_cache(maxsize=1)
def ffprobe_exe() -> str | None:
    env = os.environ.get("FFPROBE_PATH")
    if env:
        return env
    sibling = Path(ffmpeg_exe()).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
    if sibling.exists():
        return str(sibling)
    return shutil.which("ffprobe")


def _fps(text: str | None) -> float | None:
    if not text or text in ("0/0", "0"):
        return None
    try:
        if "/" in text:
            n, d = text.split("/", 1)
            return float(n) / float(d) if float(d) else None
        return float(text)
    except ValueError:
        return None


def _probe_ffprobe(path: Path) -> dict:
    out = subprocess.run([ffprobe_exe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if out.returncode != 0:
        raise ValueError("फ़ाइल पढ़ी नहीं जा सकी (ffprobe)।")
    data = json.loads(out.stdout or "{}")
    info = {"duration": None, "has_video": False, "has_audio": False, "width": None, "height": None,
            "fps": None, "rotation": 0, "is_image": False}
    try:
        info["duration"] = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        pass
    fmt = data.get("format", {}).get("format_name", "")
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"], info["height"] = s.get("width"), s.get("height")
            info["fps"] = _fps(s.get("avg_frame_rate")) or _fps(s.get("r_frame_rate"))
            rot = (s.get("tags") or {}).get("rotate")
            for sd in s.get("side_data_list") or []:
                if "rotation" in sd:
                    rot = sd["rotation"]
            info["rotation"] = int(float(rot)) % 360 if rot is not None else 0
            info["is_image"] = s.get("codec_name") in ("png", "mjpeg", "webp", "bmp") and (fmt == "image2" or fmt.endswith("_pipe"))
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VID = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+).*?(\d{2,5})x(\d{2,5})")
_FPS = re.compile(r"([\d.]+)\s*fps")
_TBR = re.compile(r"([\d.]+k?)\s*tbr")
_ROT = re.compile(r"(?:rotate\s*:\s*(-?\d+))|(?:rotation of (-?[\d.]+) degrees)")


def _probe_ffmpeg(path: Path) -> dict:
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    err = out.stderr
    if "Invalid data found" in err or "No such file" in err:
        raise ValueError("फ़ाइल पढ़ी नहीं जा सकी।")
    info = {"duration": None, "has_video": False, "has_audio": False, "width": None, "height": None,
            "fps": None, "rotation": 0, "is_image": False}
    m = _DUR.search(err)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in err.splitlines():
        if ": Video:" in line and not info["has_video"]:
            v = _VID.search(line)
            if v:
                info["has_video"] = True
                info["width"], info["height"] = int(v.group(2)), int(v.group(3))
                codec = v.group(1)
                f = _FPS.search(line) or _TBR.search(line)
                if f and not f.group(1).endswith("k"):
                    info["fps"] = float(f.group(1))
                info["is_image"] = codec in ("png", "mjpeg", "webp", "bmp") and ("image2" in err or "_pipe" in err)
        elif ": Audio:" in line:
            info["has_audio"] = True
    r = _ROT.search(err)
    if r:
        info["rotation"] = int(float(r.group(1) or r.group(2))) % 360
    return info


def probe(path: str | Path) -> dict:
    """{duration, has_video, has_audio, width, height (display, rotation applied), fps, rotation, is_image}."""
    path = Path(path)
    if not path.is_file():
        raise ValueError("फ़ाइल नहीं मिली।")
    info = _probe_ffprobe(path) if ffprobe_exe() else _probe_ffmpeg(path)
    if info["rotation"] in (90, 270) and info["width"] and info["height"]:
        info["width"], info["height"] = info["height"], info["width"]
    return info
