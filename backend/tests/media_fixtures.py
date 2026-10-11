"""Synthetic media for Workflow A tests (offline, deterministic).

Video: black frame with a 6 px white vertical bar whose x position encodes the ORIGINAL time
(x = t * W / duration), so any output frame tells us which source moment it came from.
Audio: 440 Hz tone 2.5 s on / 1.5 s off (period 4 s), so silences and A/V sync can be measured.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from app.render.ffmpeg import ffmpeg_exe

W, H, FPS, DUR = 640, 360, 30, 60.0
BAR = 6


def make_sample(path: Path, duration: float = DUR, audio: bool = True) -> Path:
    args = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={duration}",
            "-f", "lavfi", "-i", f"color=c=white:s={BAR}x{H}:r={FPS}:d={duration}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*440*t)*lt(mod(t,4),2.5)':s=48000:d={duration}"]
    args += ["-filter_complex", f"[0:v][1:v]overlay=x='t*{W}/{duration}':y=0,format=yuv420p[v]", "-map", "[v]"]
    if audio:
        args += ["-map", "2:a"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"]
    if audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    args += [str(path)]
    subprocess.run(args, check=True)
    return path


def frame_gray(video: Path, t: float, w: int = W, h: int = H) -> np.ndarray:
    raw = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8)[: w * h].reshape(h, w)


def bar_source_time(frame: np.ndarray, duration: float = DUR, rows: slice = slice(0, 40)) -> float:
    """Source time encoded by the bar (top rows only, away from captions)."""
    cols = frame[rows].astype(float).mean(axis=0)
    bright = np.where(cols > 128)[0]
    if bright.size == 0:
        raise AssertionError("bar not found")
    left = bright.min()
    return left * duration / frame.shape[1]


def save_png(frame_path: Path, video: Path, t: float) -> None:
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                    "-frames:v", "1", str(frame_path)], check=True)


def audio_onsets(video: Path, sr: int = 8000, win_s: float = 0.01, thresh: float = 0.05) -> list[float]:
    raw = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768
    n = int(sr * win_s)
    env = np.sqrt((x[: len(x) // n * n].reshape(-1, n) ** 2).mean(axis=1))
    on = env > thresh
    return [i * win_s for i in range(1, len(on)) if on[i] and not on[i - 1]]
