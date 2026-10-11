"""Devanagari-capable caption font (PRD §11.2).

Order: bundled files in backend/app/assets/fonts (Noto Sans Devanagari, if added) → system Noto
(Docker image: fonts-noto-core) → Windows "Nirmala UI" (local dev). The chosen files are copied into
the render folder and passed to libass via `fontsdir`, so rendering never depends on a font cache.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_CANDIDATES: list[tuple[str, list[Path]]] = [
    ("Noto Sans Devanagari", sorted(ASSETS.glob("NotoSansDevanagari*.ttf"))),
    ("Noto Sans Devanagari", [Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
                              Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf")]),
    ("Nirmala UI", [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / n for n in ("Nirmala.ttf", "NirmalaB.ttf")]),
]


@lru_cache(maxsize=1)
def caption_font() -> tuple[str, list[Path]]:
    """(family name for ASS styles, font files). Raises if no Devanagari font is available."""
    override = os.environ.get("CAPTION_FONT_FILE")
    if override and Path(override).is_file():
        return os.environ.get("CAPTION_FONT_FAMILY", "Noto Sans Devanagari"), [Path(override)]
    for family, files in _CANDIDATES:
        existing = [f for f in files if f.is_file()]
        if existing:
            return family, existing
    raise RuntimeError("Devanagari font नहीं मिला — Noto Sans Devanagari install करें (CAPTION_FONT_FILE)।")


def stage_fonts(dest_dir: Path) -> str:
    """Copy the caption font files into dest_dir; returns the family name."""
    family, files = caption_font()
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        target = dest_dir / f.name
        if not target.exists():
            shutil.copyfile(f, target)
    return family
