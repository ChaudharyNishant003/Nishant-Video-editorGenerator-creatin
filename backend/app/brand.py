"""Brand kit (handoff §6 extras): logo watermark, accent colour, intro/outro clips.

Files live in DATA_DIR/brand/ (logo.png|jpg|webp, intro.<ext>, outro.<ext>); settings are non-secret
preferences (`brand.*`). Applied to Workflow A and/or B outputs depending on the toggles.
"""

from __future__ import annotations

from pathlib import Path

from . import db
from .config import settings
from .create.compose import Brand, hex_to_bgr

KINDS = {"logo": {".png", ".jpg", ".jpeg", ".webp"}, "intro": {".mp4", ".mov", ".webm", ".m4v", ".mkv"},
         "outro": {".mp4", ".mov", ".webm", ".m4v", ".mkv"}}
POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")
DEFAULTS = {"brand.position": "top_right", "brand.opacity": "0.8", "brand.scale": "0.12", "brand.accent": "",
            "brand.apply_edit": "0", "brand.apply_create": "0", "brand.intro": "1", "brand.outro": "1"}


def brand_dir() -> Path:
    d = settings.data_dir / "brand"
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_for(kind: str) -> Path | None:
    for f in sorted(brand_dir().glob(f"{kind}.*")):
        if f.suffix.lower() in KINDS[kind]:
            return f
    return None


def prefs() -> dict[str, str]:
    with db.locked() as c:
        rows = c.execute("SELECT key, value FROM preferences WHERE key LIKE 'brand.%'").fetchall()
    out = dict(DEFAULTS)
    out.update({r["key"]: r["value"] for r in rows})
    return out


def _float(v: str, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def state() -> dict:
    p = prefs()
    return {"position": p["brand.position"] if p["brand.position"] in POSITIONS else "top_right",
            "opacity": _float(p["brand.opacity"], 0.1, 1.0, 0.8), "scale": _float(p["brand.scale"], 0.04, 0.3, 0.12),
            "accent": p["brand.accent"] if hex_to_bgr(p["brand.accent"]) else "",
            "apply_edit": p["brand.apply_edit"] == "1", "apply_create": p["brand.apply_create"] == "1",
            "intro": p["brand.intro"] == "1", "outro": p["brand.outro"] == "1",
            "files": {k: (file_for(k).name if file_for(k) else None) for k in KINDS}}


def load(workflow: str) -> tuple[Brand, Path | None, Path | None]:
    """(Brand for overlays, intro clip, outro clip) for 'edit' or 'create'; empty Brand if not enabled."""
    st = state()
    if not st["apply_edit" if workflow == "edit" else "apply_create"]:
        return Brand(), None, None
    brand = Brand(logo=file_for("logo"), position=st["position"], opacity=st["opacity"], scale=st["scale"],
                  accent=st["accent"] or None)
    return brand, (file_for("intro") if st["intro"] else None), (file_for("outro") if st["outro"] else None)


def signature(b: Brand) -> str:
    logo = b.logo
    stamp = f"{logo.name}:{logo.stat().st_mtime_ns}" if logo and logo.is_file() else "-"
    return f"{stamp}|{b.position}|{b.opacity}|{b.scale}|{b.accent}"
