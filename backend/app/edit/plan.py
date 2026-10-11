"""Workflow A edit plan: schema + validation/repair (PRD §4.2, §4.3).

All times are seconds on the ORIGINAL timeline. validate_plan() never raises for bad individual
ops: it clamps, merges, drops and explains everything in Hindi `warnings`. It raises PlanError only
when the result cannot be rendered at all (e.g. everything would be cut).
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

POSITIONS = ("top_left", "top_center", "top_right", "center", "bottom_left", "bottom_center", "bottom_right")
OVERLAY_STYLES = ("bold_yellow", "white_box", "red_bold", "plain_white")
CAPTION_STYLES = ("hindi_bold_word_highlight", "line")
FOCUS = ("center", "left", "right", "top", "bottom")
RANGED = ("cut", "text_overlay", "zoom", "speed", "broll")
SINGLETONS = ("captions", "music", "audio_cleanup")
MIN_KEEP_S = 0.5
OP_LABEL = {"cut": "कट", "remove_silence": "खामोशी हटाओ", "captions": "कैप्शन", "text_overlay": "टेक्स्ट",
            "zoom": "ज़ूम", "speed": "स्पीड", "music": "म्यूज़िक", "broll": "B-roll", "audio_cleanup": "ऑडियो सफ़ाई"}


class PlanError(ValueError):
    pass


class PlanTooShort(PlanError):
    """The plan is well-formed but would cut (almost) the whole video."""


class _Op(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    proposed_by_ai: bool = False
    note: str = ""


class CutOp(_Op):
    type: Literal["cut"]
    start: float
    end: float


class RemoveSilenceOp(_Op):
    type: Literal["remove_silence"]
    min_silence_ms: int = 600
    threshold_db: float = -35.0
    start: float | None = None
    end: float | None = None


class CaptionsOp(_Op):
    type: Literal["captions"]
    style: str = "hindi_bold_word_highlight"
    language: str = "hi"
    start: float | None = None
    end: float | None = None


class TextOverlayOp(_Op):
    type: Literal["text_overlay"]
    start: float
    end: float
    text: str
    position: str = "bottom_center"
    style: str = "bold_yellow"


class ZoomOp(_Op):
    type: Literal["zoom"]
    start: float
    end: float
    scale: float = 1.3
    focus: str = "center"


class SpeedOp(_Op):
    type: Literal["speed"]
    start: float
    end: float
    factor: float


class MusicOp(_Op):
    type: Literal["music"]
    track: str
    volume: float = 0.15
    duck: bool = True


class BrollOp(_Op):
    type: Literal["broll"]
    start: float
    end: float
    source: str
    mode: Literal["overlay", "replace"] = "overlay"


class AudioCleanupOp(_Op):
    type: Literal["audio_cleanup"]
    denoise: bool = True
    loudnorm: bool = True


Op = Annotated[Union[CutOp, RemoveSilenceOp, CaptionsOp, TextOverlayOp, ZoomOp, SpeedOp, MusicOp, BrollOp,
                     AudioCleanupOp], Field(discriminator="type")]
_OP = TypeAdapter(Op)


class Plan(BaseModel):
    version: int = 1
    source_duration_s: float
    ops: list[Op] = []
    warnings: list[str] = []
    question: str | None = None


_TIME = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)\s*$|^\s*(\d+(?:\.\d+)?)\s*s?\s*$")


def parse_time(v: Any) -> float | None:
    """Seconds from 65, "65", "65.5s", "1:05", "1:05.5", "0:01:05"."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _TIME.match(str(v))
    if not m:
        raise ValueError(f"समय समझ नहीं आया: '{v}'")
    if m.group(4) is not None:
        return float(m.group(4))
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def fmt_time(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:04.1f}"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def validate_plan(raw: dict, duration: float, asset_ids: set[str] | None = None) -> Plan:
    """Turn untrusted plan JSON (LLM or UI) into a safe Plan; problems become Hindi warnings."""
    if not isinstance(raw, dict):
        raise PlanError("प्लान JSON object नहीं है।")
    ops_in = raw.get("ops")
    if ops_in is None:
        ops_in = []
    if not isinstance(ops_in, list):
        raise PlanError("प्लान में 'ops' सूची नहीं है।")
    warnings: list[str] = [str(w)[:300] for w in (raw.get("warnings") or []) if isinstance(w, (str, int, float))]
    question = raw.get("question")
    question = str(question).strip()[:500] if question else None
    D = round(float(duration), 3)
    ops: list[Any] = []

    for i, item in enumerate(ops_in[:200], 1):
        if not isinstance(item, dict):
            warnings.append(f"Op #{i} समझ नहीं आया, छोड़ दिया।")
            continue
        item = dict(item)
        kind = item.get("type")
        label = OP_LABEL.get(kind, str(kind))
        try:
            for k in ("start", "end"):
                if k in item:
                    item[k] = parse_time(item[k])
            op = _OP.validate_python(item)
        except (ValidationError, ValueError) as e:
            msg = e.errors()[0].get("msg", "") if isinstance(e, ValidationError) else str(e)
            warnings.append(f"Op #{i} ({label}) अमान्य था, छोड़ दिया: {msg[:120]}")
            continue

        # time range checks (original timeline)
        has_range = getattr(op, "start", None) is not None or getattr(op, "end", None) is not None
        if op.type in RANGED or has_range:
            start = op.start if op.start is not None else 0.0
            end = op.end if op.end is not None else D
            if end > D + 1e-6:
                warnings.append(f"{label}: समय {fmt_time(end)} वीडियो की लंबाई ({fmt_time(D)}) से आगे था — अंत तक सीमित किया।")
            if start < 0:
                warnings.append(f"{label}: शुरुआत 0 से पहले थी — 0 किया।")
            start, end = round(_clamp(start, 0, D), 3), round(_clamp(end, 0, D), 3)
            if start >= end:
                warnings.append(f"{label}: शुरुआत ({fmt_time(start)}) अंत ({fmt_time(end)}) से पहले नहीं — छोड़ दिया।")
                continue
            if op.type in RANGED or op.start is not None or op.end is not None:
                op.start, op.end = start, end

        # parameter checks
        if op.type == "zoom":
            s = _clamp(op.scale, 1.1, 2.0)
            if abs(s - op.scale) > 1e-9:
                warnings.append(f"ज़ूम {op.scale} → {s} (1.1–2.0 की सीमा)।")
            op.scale = round(s, 3)
            if op.focus not in FOCUS:
                op.focus = "center"
        elif op.type == "speed":
            f = _clamp(op.factor, 0.5, 2.0)
            if abs(f - op.factor) > 1e-9:
                warnings.append(f"स्पीड {op.factor}× → {f}× (0.5–2.0 की सीमा)।")
            if abs(f - 1.0) < 1e-3:
                warnings.append("स्पीड 1× का कोई असर नहीं — छोड़ दिया।")
                continue
            op.factor = round(f, 3)
        elif op.type == "remove_silence":
            op.min_silence_ms = int(_clamp(op.min_silence_ms, 200, 5000))
            op.threshold_db = _clamp(op.threshold_db, -70, -10)
        elif op.type == "captions":
            if op.style not in CAPTION_STYLES:
                warnings.append(f"कैप्शन style '{op.style}' नहीं है — डिफ़ॉल्ट लगाया।")
                op.style = CAPTION_STYLES[0]
        elif op.type == "text_overlay":
            op.text = op.text.strip()[:160]
            if not op.text:
                warnings.append("ख़ाली टेक्स्ट overlay छोड़ दिया।")
                continue
            if op.position not in POSITIONS:
                op.position = "bottom_center"
            if op.style not in OVERLAY_STYLES:
                op.style = "bold_yellow"
        elif op.type == "music":
            op.volume = round(_clamp(op.volume, 0.0, 1.0), 3)
            aid = op.track.split(":", 1)[1] if op.track.startswith("upload:") else op.track
            op.track = f"upload:{aid}"
            if asset_ids is not None and aid not in asset_ids:
                warnings.append("म्यूज़िक: चुना गया track नहीं मिला — पहले म्यूज़िक फ़ाइल जोड़ें।")
                continue
        elif op.type == "broll":
            src = op.source.strip()
            if src.startswith("stock:") and src[6:].strip():
                op.source = "stock:" + src[6:].strip()[:100]
            elif src.startswith("upload:"):
                if asset_ids is not None and src[7:] not in asset_ids:
                    warnings.append("B-roll: चुनी गई फ़ाइल नहीं मिली — छोड़ दिया।")
                    continue
            else:
                warnings.append(f"B-roll source '{src[:40]}' समझ नहीं आया (stock:<query> या upload:<id>) — छोड़ दिया।")
                continue
        ops.append(op)

    ops = _dedupe(ops, warnings)
    seen: set[str] = set()
    for n, op in enumerate(ops, 1):
        if not op.id or op.id in seen:
            op.id = f"op{n}"
            while op.id in seen:
                op.id += "_"
        seen.add(op.id)

    plan = Plan(source_duration_s=D, ops=ops, warnings=list(dict.fromkeys(warnings)), question=question)
    kept = D - sum(b - a for a, b in merged_cuts(plan))
    if kept < MIN_KEEP_S:
        raise PlanTooShort("इस प्लान से लगभग पूरा वीडियो कट हो जाएगा — कट कम करें।")
    return plan


def _overlaps(a, b) -> bool:
    return a.start < b.end and b.start < a.end


def _dedupe(ops: list, warnings: list[str]) -> list:
    out: list = []
    for op in ops:
        if op.type in SINGLETONS and any(o.type == op.type for o in out):
            warnings.append(f"{OP_LABEL[op.type]} एक से ज़्यादा बार था — पहला रखा।")
            continue
        if op.type in ("zoom", "speed", "broll"):
            clash = next((o for o in out if o.type == op.type and _overlaps(o, op)), None)
            if clash:
                warnings.append(f"{OP_LABEL[op.type]} {fmt_time(op.start)}–{fmt_time(op.end)} दूसरे {OP_LABEL[op.type]} से टकराता है — छोड़ दिया।")
                continue
        out.append(op)
    cuts = [o for o in out if o.type == "cut"]
    if len(merged_cuts(Plan(source_duration_s=1e9, ops=cuts))) < len(cuts):
        warnings.append("कुछ कट आपस में टकरा रहे थे — उन्हें जोड़ दिया।")
    return out


def merged_cuts(plan: Plan) -> list[tuple[float, float]]:
    """Explicit cuts merged into non-overlapping, sorted ranges."""
    ranges = sorted((o.start, o.end) for o in plan.ops if o.type == "cut")
    return merge_ranges(ranges)


def merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]
