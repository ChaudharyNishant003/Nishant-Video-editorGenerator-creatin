"""ASS subtitle writer for captions + text overlays (PRD §11.2). User text only ever goes into the
ASS file, never into an ffmpeg filter string."""

from __future__ import annotations

from .timemap import TimeMap

WHITE, YELLOW, BLACK, RED = "&H00FFFFFF", "&H0000FFFF", "&H00000000", "&H003030FF"
ALIGN = {"bottom_left": 1, "bottom_center": 2, "bottom_right": 3, "center": 5,
         "top_left": 7, "top_center": 8, "top_right": 9}
PUNCT_END = ("।", "?", "!", ".", "॥")


def ass_text(s: str) -> str:
    """Neutralise ASS override syntax in user/LLM text."""
    return (s.replace("\\", "＼").replace("{", "(").replace("}", ")")
             .replace("\r", "").replace("\n", "\\N"))


def ass_ts(t: float) -> str:
    cs = max(0, round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _styles(font: str, w: int, h: int) -> list[str]:
    base = min(w, h)
    portrait = h > w
    cap = round(base * (0.068 if portrait else 0.064))
    ov = round(base * 0.072)
    mv = round(h * (0.20 if portrait else 0.07))
    m = round(w * 0.05)
    fields = "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"

    def st(name, size, primary, outline, back, bold, border, outw, shadow, align, mv_):
        return f"Style: {name},{font},{size},{primary},{YELLOW},{outline},{back},{bold},0,0,0,100,100,0,0,{border},{outw},{shadow},{align},{m},{m},{mv_},1"

    return [f"Format: {fields}",
            st("Caption", cap, WHITE, BLACK, "&H96000000", -1, 1, max(2, cap // 14), 1, 2, mv),
            st("bold_yellow", ov, YELLOW, BLACK, "&H96000000", -1, 1, max(2, ov // 12), 1, 2, mv),
            st("white_box", ov, BLACK, WHITE, WHITE, -1, 3, max(4, ov // 6), 0, 2, mv),
            st("red_bold", ov, RED, WHITE, "&H96000000", -1, 1, max(2, ov // 12), 1, 2, mv),
            st("plain_white", ov, WHITE, "&H50000000", "&H96000000", 0, 1, max(1, ov // 24), 2, 2, mv)]


def group_words(words: list[dict], max_words: int, max_gap: float = 0.6, max_span: float = 3.0) -> list[list[dict]]:
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > max_gap
                    or w["end"] - cur[0]["start"] > max_span or cur[-1]["text"].endswith(PUNCT_END)):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def remap_words(words: list[dict], tm: TimeMap, rng: tuple[float, float] | None = None) -> list[dict]:
    """Map transcript words (original time) to output time; words whose middle was cut are dropped."""
    out = []
    for w in words:
        text = (w.get("text") or "").strip()
        if not text:
            continue
        a, b = float(w["start"]), float(w["end"])
        if rng and not (rng[0] <= (a + b) / 2 <= rng[1]):
            continue
        mid = tm.map_time((a + b) / 2)
        if mid is None:
            continue
        parts = tm.map_range(a, b)
        part = next((p for p in parts if p[0] - 1e-6 <= mid <= p[1] + 1e-6), (mid, mid + 0.05))
        out.append({"text": text, "start": part[0], "end": max(part[1], part[0] + 0.05)})
    return out


def caption_events(words: list[dict], style: str) -> list[str]:
    events = []
    highlight = style == "hindi_bold_word_highlight"
    groups = group_words(words, 4 if highlight else 7)
    for gi, g in enumerate(groups):
        g_end = g[-1]["end"] + 0.25
        if gi + 1 < len(groups):  # never overlap the next group (libass would stack both lines)
            g_end = max(g[-1]["end"], min(g_end, groups[gi + 1][0]["start"]))
        if not highlight:
            events.append(f"Dialogue: 0,{ass_ts(g[0]['start'])},{ass_ts(g_end)},Caption,,0,0,0,,"
                          + " ".join(ass_text(w["text"]) for w in g))
            continue
        for i, w in enumerate(g):
            end = g[i + 1]["start"] if i + 1 < len(g) else g_end
            if end - w["start"] < 0.02:
                continue
            text = " ".join(("{\\c&H00FFFF&}" + ass_text(x["text"]) + "{\\c&HFFFFFF&}") if j == i else ass_text(x["text"])
                            for j, x in enumerate(g))
            events.append(f"Dialogue: 0,{ass_ts(w['start'])},{ass_ts(end)},Caption,,0,0,0,,{text}")
    return events


def ass_header(font: str, w: int, h: int) -> list[str]:
    return ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0",
            "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", *_styles(font, w, h), "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]


def build_scene_ass(font: str, w: int, h: int, words: list[dict], style: str | None,
                    extra_events: list[str] | None = None) -> str:
    """Workflow B: captions for one scene whose word timings are already scene-local (no time map)."""
    events = caption_events([w for w in words if (w.get("text") or "").strip()], style) if style and words else []
    return "\n".join(ass_header(font, w, h) + events + list(extra_events or [])) + "\n"


def build_ass(font: str, w: int, h: int, tm: TimeMap, words: list[dict] | None, captions_op, overlays: list) -> tuple[str, int]:
    """Returns (ass file text, number of caption words used)."""
    events: list[str] = []
    used = 0
    if captions_op is not None and words:
        rng = (captions_op.start, captions_op.end) if captions_op.start is not None else None
        mapped = remap_words(words, tm, rng)
        used = len(mapped)
        events += caption_events(mapped, captions_op.style)
    for op in overlays:
        for oa, ob in tm.map_range(op.start, op.end):
            align = ALIGN.get(op.position, 2)
            events.append(f"Dialogue: 1,{ass_ts(oa)},{ass_ts(ob)},{op.style},,0,0,0,,{{\\an{align}}}{ass_text(op.text)}")
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0",
            "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", *_styles(font, w, h), "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    return "\n".join(head + events) + "\n", used
