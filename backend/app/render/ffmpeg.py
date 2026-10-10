"""Locating ffmpeg. Commands are always argument arrays, never shell strings (PRD §11.1)."""

import os
import shutil
from functools import lru_cache


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    env = os.environ.get("FFMPEG_PATH")
    if env:
        return env
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    import imageio_ffmpeg  # bundled binary (has libass + HarfBuzz; verified 2026-10-10)

    return imageio_ffmpeg.get_ffmpeg_exe()
