"""Workflow A jobs: ingest (CFR normalise), transcribe (STT with fallback), render (PRD §11.3)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import requests

from .. import db, storage
from ..jobs import JobCancelled, JobContext
from ..providers import registry
from ..providers.base import ProviderError
from ..render.fonts import stage_fonts
from ..render.probe import probe
from .captions import build_ass
from .plan import OP_LABEL, Plan, fmt_time, merged_cuts, merge_ranges
from .timemap import Piece, TimeMap, build_timemap

MAX_SHORT_SIDE = 720
MAX_FPS = 30  # PRD keeps source fps; capped at 30 so a 3-min edit stays near the 5-min budget on a 2-core CPU
SILENCE_PAD_S = 0.12
STOCK_MAX_BYTES = 150 * 1024 * 1024
FOCUS = {"center": (0.5, 0.5), "left": (0.0, 0.5), "right": (1.0, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0)}


def get_pref(key: str) -> str | None:
    with db.locked() as c:
        row = c.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def latest_transcript(project_id: str) -> dict | None:
    with db.locked() as c:
        row = c.execute("SELECT * FROM transcripts WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
                        (project_id,)).fetchone()
    return db.row_to_dict(row)


def save_transcript(project_id: str, provider: str, language: str, words: list[dict]) -> None:
    with db.locked() as c:
        c.execute("DELETE FROM transcripts WHERE project_id=?", (project_id,))
        c.execute("INSERT INTO transcripts(id, project_id, provider, language, words_json, created_at) VALUES (?,?,?,?,?,?)",
                  (db.new_id(), project_id, provider, language, json.dumps(words, ensure_ascii=False), db.now()))


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def target_geometry(width: int, height: int, fps: float | None) -> tuple[int, int, int]:
    s = min(1.0, MAX_SHORT_SIDE / min(width, height))
    f = int(round(fps)) if fps and fps > 1 else 30
    return _even(width * s), _even(height * s), max(15, min(MAX_FPS, f))


# --- ingest --------------------------------------------------------------------------------------
def ingest(ctx: JobContext, project_id: str, source: dict) -> dict:
    info = source["meta"]["probe"]
    d = storage.project_dir(project_id)
    W, H, fps = target_geometry(info["width"], info["height"], info.get("fps"))
    dur = float(info["duration"])
    work, audio = d / "work.mp4", d / "audio.flac"
    ctx.log(f"Ingest: {info['width']}×{info['height']} @ {info.get('fps') or '?'} fps → {W}×{H} @ {fps} fps (CFR)।")
    args = ["-i", source["path"]]
    if not info["has_audio"]:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        ctx.log("वीडियो में आवाज़ नहीं है — खामोश audio track जोड़ा।", "warn")
    args += ["-map", "0:v:0", "-map", "0:a:0" if info["has_audio"] else "1:a:0",
             "-vf", f"scale={W}:{H}:flags=bicubic,setsar=1,fps={fps},format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", str(fps),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{dur:.3f}",
             "-movflags", "+faststart", str(work)]
    try:
        storage.set_status(project_id, "ingesting")
        ctx.run_ffmpeg(args, expected_duration_s=dur, pct_from=2, pct_to=85, step="ingest")
        ctx.run_ffmpeg(["-i", str(work), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(audio)],
                       expected_duration_s=dur, pct_from=85, pct_to=97, step="audio")
        wi = probe(work)
        for old in storage.list_assets(project_id, ("work",)):
            _delete_asset_row(old["id"])
        a = storage.add_asset(project_id, "work", work, "video/mp4", wi["duration"],
                              {"name": "work.mp4", "width": W, "height": H, "fps": fps,
                               "source_has_audio": info["has_audio"], "audio_path": str(audio)})
        storage.set_status(project_id, "ingested")
    except Exception:
        storage.set_status(project_id, "ingest_failed")
        raise
    ctx.log(f"Ingest पूरा: {fmt_time(wi['duration'])}।")
    return {"work_asset_id": a["id"], "duration_s": wi["duration"], "width": W, "height": H, "fps": fps}


def _delete_asset_row(asset_id: str) -> None:
    with db.locked() as c:
        c.execute("DELETE FROM assets WHERE id=?", (asset_id,))


# --- transcribe ----------------------------------------------------------------------------------
def transcribe(ctx: JobContext, project_id: str, language: str) -> dict:
    work = storage.latest_asset(project_id, "work")
    if work is None:
        raise RuntimeError("पहले वीडियो ingest होना चाहिए।")
    audio = Path(work["meta"]["audio_path"])
    if not work["meta"].get("source_has_audio", True):
        save_transcript(project_id, "none", language, [])
        ctx.log("वीडियो में आवाज़ नहीं — transcript ख़ाली; कैप्शन नहीं बनेंगे।", "warn")
        return {"words": 0, "provider": None}
    ctx.progress(10, "stt")
    storage.set_status(project_id, "transcribing")

    def call(p, keys):
        ctx.check_cancelled()
        ctx.log(f"{p.label} से transcript बन रहा है…")
        return p.impl(audio, keys, language=language)

    try:
        res, prov = registry.run_with_fallback("stt", get_pref("default.stt"), ctx.keys, call,
                                               notify=lambda m: ctx.log(m, "warn"))
    except Exception:
        storage.set_status(project_id, "transcribe_failed")
        raise
    words = [w for w in res["words"] if w.get("text")]
    save_transcript(project_id, prov.id, res.get("language") or language, words)
    storage.set_status(project_id, "transcribed")
    if not words:
        ctx.log("कोई बोले गए शब्द नहीं मिले — कैप्शन नहीं बनेंगे।", "warn")
    ctx.log(f"Transcript तैयार: {len(words)} शब्द ({prov.label})।")
    return {"words": len(words), "provider": prov.id}


# --- render --------------------------------------------------------------------------------------
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def parse_silences(lines: list[str], offset: float, limit_end: float) -> list[tuple[float, float]]:
    out, start = [], None
    for line in lines:
        if (m := _SIL_START.search(line)):
            start = max(0.0, float(m.group(1))) + offset
        elif (m := _SIL_END.search(line)) and start is not None:
            out.append((start, min(limit_end, float(m.group(1)) + offset)))
            start = None
    if start is not None:
        out.append((start, limit_end))
    return out


def silence_cuts(silences: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Keep a little air around speech so words are not clipped."""
    cuts = []
    for a, b in silences:
        ca = a if a <= 0.01 else a + SILENCE_PAD_S
        cb = b if b >= duration - 0.01 else b - SILENCE_PAD_S
        if cb - ca >= 0.1:
            cuts.append((round(ca, 3), round(cb, 3)))
    return cuts


def _zoom_expr(p: Piece) -> tuple[str, float, float]:
    """zoompan z-expression: ease in/out over R seconds at the zoom's ORIGINAL start/end (it = piece-local time)."""
    z = p.zoom
    R = min(0.5, (z.end - z.start) / 3)
    src = f"({p.src_start:.4f}+it*{p.factor:.4f})"
    expr = (f"st(0,clip(min(({src}-{z.start:.4f})/{R:.4f},({z.end:.4f}-{src})/{R:.4f}),0,1));"
            f"1+{z.scale - 1:.4f}*ld(0)*ld(0)*(3-2*ld(0))")
    fx, fy = FOCUS.get(z.focus, (0.5, 0.5))
    return expr, fx, fy


def segment_args(work: str, p: Piece, W: int, H: int, fps: int, out: str) -> list[str]:
    vf = [f"setpts=(PTS-STARTPTS)/{p.factor:.6f}", f"fps={fps}"]
    if p.zoom is not None:
        # after fps= so zoompan's 1 frame in → 1 frame out keeps timing (crop can't follow per-frame size changes)
        expr, fx, fy = _zoom_expr(p)
        vf.append(f"zoompan=z='{expr}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}':d=1:s={W}x{H}:fps={fps}")
    vf += ["tpad=stop_mode=clone:stop_duration=2", f"trim=end_frame={p.out_frames}",
           "setpts=PTS-STARTPTS", "setsar=1", "format=yuv420p"]
    af = ["asetpts=PTS-STARTPTS"]
    if abs(p.factor - 1) > 1e-6:
        af.append(f"atempo={p.factor:.6f}")
    af += ["aresample=48000", f"apad=whole_dur={p.out_dur:.6f}", f"atrim=end={p.out_dur:.6f}", "asetpts=PTS-STARTPTS"]
    return ["-ss", f"{p.src_start:.4f}", "-t", f"{p.src_dur:.4f}", "-i", work,
            "-vf", ",".join(vf), "-af", ",".join(af),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            out]


def fetch_stock(ctx: JobContext, query: str, dest: Path) -> tuple[Path, str, bool]:
    """Search stock (Pexels → Pixabay fallback), download the first usable clip/photo."""
    def call(p, keys):
        items = p.impl(query, keys, kind="video", per_page=5)
        kind = "video"
        if not items:
            items, kind = p.impl(query, keys, kind="photo", per_page=5), "photo"
        if not items:
            raise ProviderError("bad_output", f"{p.label}: '{query}' के लिए कुछ नहीं मिला।")
        return items[0], kind

    (item, kind), prov = registry.run_with_fallback("stock", get_pref("default.stock"), ctx.keys, call,
                                                    notify=lambda m: ctx.log(m, "warn"))
    ext = ".mp4" if kind == "video" else ".jpg"
    path = dest / ("stock_" + hashlib.sha256(item["url"].encode()).hexdigest()[:16] + ext)
    if not path.exists():
        tmp = path.with_suffix(".part")
        with requests.get(item["url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            size = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    size += len(chunk)
                    if size > STOCK_MAX_BYTES:
                        raise ProviderError("error", "Stock फ़ाइल बहुत बड़ी है।")
                    f.write(chunk)
        tmp.replace(path)
    return path, item.get("attribution") or prov.label, kind == "photo"


def render(ctx: JobContext, project_id: str, plan: Plan, plan_version: int) -> dict:
    t0 = time.time()
    storage.set_status(project_id, "rendering")
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + ctx.id[:6]
    rdir = storage.project_dir(project_id) / "renders" / rid
    try:
        result = _render(ctx, project_id, plan, plan_version, rid, rdir)
    except BaseException as e:
        shutil.rmtree(rdir, ignore_errors=True)  # no half-finished segments left on disk
        if isinstance(e, JobCancelled):
            storage.set_status(project_id, "done" if storage.list_assets(project_id, ("output",)) else "planned")
        else:
            storage.set_status(project_id, "render_failed")
        raise
    storage.set_status(project_id, "done")
    result["render_seconds"] = round(time.time() - t0, 1)
    ctx.log(f"रेंडर पूरा: {fmt_time(result['duration_s'])} वीडियो, {result['render_seconds']} सेकंड में।")
    return result


def _render(ctx: JobContext, project_id: str, plan: Plan, plan_version: int, rid: str, rdir: Path) -> dict:
    work = storage.latest_asset(project_id, "work")
    if work is None:
        raise RuntimeError("पहले वीडियो ingest होना चाहिए।")
    m = work["meta"]
    W, H, fps, D = m["width"], m["height"], m["fps"], float(work["duration_s"])
    rdir.mkdir(parents=True, exist_ok=True)
    notices: list[str] = []

    def notice(msg: str) -> None:
        notices.append(msg)
        ctx.log(msg, "warn")

    by_type: dict[str, list] = {}
    for op in plan.ops:
        by_type.setdefault(op.type, []).append(op)

    # 1) cuts = explicit cuts + silence cuts (original time)
    cuts = merged_cuts(plan)
    for op in by_type.get("remove_silence", []):
        a = op.start if op.start is not None else 0.0
        b = op.end if op.end is not None else D
        lines = ctx.run_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", work["path"], "-vn",
                                "-af", f"silencedetect=noise={op.threshold_db:.1f}dB:d={op.min_silence_ms / 1000:.3f}",
                                "-f", "null", "-"], step="silence", pct_from=1, pct_to=4, collect_stderr=True)
        sc = silence_cuts(parse_silences(lines, a, b), D)
        ctx.log(f"खामोशी: {len(sc)} हिस्से मिले, कुल {sum(y - x for x, y in sc):.1f} सेकंड हटेंगे।")
        cuts += sc
    cuts = merge_ranges(cuts)
    tm = build_timemap(D, fps, cuts, by_type.get("speed", []), by_type.get("zoom", []))
    if not tm.pieces or tm.total < 0.5:
        raise RuntimeError("कट के बाद कुछ नहीं बचा।")
    ctx.log(f"Time map: {len(tm.pieces)} हिस्से, {fmt_time(D)} → {fmt_time(tm.total)}।")

    # 2) segments (each: cut + speed + zoom, frame-exact) → concat list
    seg_total = sum(p.src_dur for p in tm.pieces)
    done = 0.0
    names = []
    for i, p in enumerate(tm.pieces):
        name = f"seg_{i:04d}.mkv"
        lo = 5 + 50 * done / seg_total
        done += p.src_dur
        ctx.run_ffmpeg(segment_args(work["path"], p, W, H, fps, name), expected_duration_s=p.out_dur,
                       pct_from=lo, pct_to=5 + 50 * done / seg_total, step=f"segment {i + 1}/{len(tm.pieces)}", cwd=str(rdir))
        names.append(name)
    (rdir / "segments.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")

    # 3) inputs for the final pass
    inputs = ["-f", "concat", "-safe", "0", "-i", "segments.txt"]
    n_in = 1
    vfilters: list[str] = []
    vlabel = "[0:v]"
    attributions: list[str] = []
    for op in by_type.get("broll", []):
        try:
            if op.source.startswith("stock:"):
                ctx.progress(56, "b-roll")
                path, attrib, is_image = fetch_stock(ctx, op.source[6:], storage.project_dir(project_id))
                attributions.append(attrib)
            else:
                asset = storage.get_asset(op.source[7:])
                if asset is None or asset["project_id"] != project_id:
                    raise ProviderError("error", "फ़ाइल नहीं मिली")
                path, is_image = Path(asset["path"]), bool((asset.get("meta") or {}).get("probe", {}).get("is_image"))
        except ProviderError as e:
            notice(f"B-roll {fmt_time(op.start)}–{fmt_time(op.end)} छोड़ा: {e}")
            continue
        for oa, ob in tm.map_range(op.start, op.end):
            if is_image:
                inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(path)]
            else:
                inputs += ["-stream_loop", "-1", "-i", str(path)]
            k = n_in
            n_in += 1
            if op.mode == "replace":
                fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
                pos = "x=0:y=0"
            else:
                bw = _even(W * 0.38)
                fit = f"scale={bw}:-2,pad=iw+8:ih+8:4:4:white"
                pos = f"x=W-w-{round(W * 0.03)}:y={round(H * 0.04)}"
            vfilters.append(f"[{k}:v]trim=duration={ob - oa:.3f},setpts=PTS-STARTPTS+{oa:.3f}/TB,{fit},setsar=1,fps={fps},format=yuv420p[b{k}]")
            vfilters.append(f"{vlabel}[b{k}]overlay={pos}:enable='between(t,{oa:.3f},{ob:.3f})':eof_action=pass[v{k}]")
            vlabel = f"[v{k}]"

    captions = (by_type.get("captions") or [None])[0]
    overlays = by_type.get("text_overlay", [])
    words = None
    if captions is not None:
        tr = latest_transcript(project_id)
        words = (tr or {}).get("words") or []
        if not words:
            notice("कैप्शन छोड़े: transcript में बोले गए शब्द नहीं हैं।")
            captions = None
    used_words = 0
    if captions is not None or overlays:
        family = stage_fonts(rdir / "fonts")
        ass, used_words = build_ass(family, W, H, tm, words, captions, overlays)
        (rdir / "subs.ass").write_text(ass, encoding="utf-8")
        # `ass` (not `subtitles`) + shaping=complex: HarfBuzz shaping, required for Devanagari conjuncts/matras
        vfilters.append(f"{vlabel}ass=filename=subs.ass:fontsdir=fonts:shaping=complex[vs]")
        vlabel = "[vs]"
        if captions is not None:
            ctx.log(f"कैप्शन: {used_words} शब्द ({captions.style}), font {family}।")

    T = tm.total
    afilters: list[str] = []
    alabel = "[0:a]"
    cleanup = (by_type.get("audio_cleanup") or [None])[0]
    if cleanup is not None and cleanup.denoise:
        afilters.append(f"{alabel}afftdn=nf=-25[ad]")
        alabel = "[ad]"
    music = (by_type.get("music") or [None])[0]
    if music is not None:
        asset = storage.get_asset(music.track.split(":", 1)[1])
        if asset is None or asset["project_id"] != project_id:
            notice("म्यूज़िक फ़ाइल नहीं मिली — म्यूज़िक छोड़ा।")
        else:
            inputs += ["-stream_loop", "-1", "-i", asset["path"]]
            k = n_in
            n_in += 1
            afilters.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={T:.3f},"
                            f"volume={music.volume:.3f},afade=t=in:d=1,afade=t=out:st={max(0.0, T - 2):.3f}:d=2[mus]")
            if music.duck:
                afilters.append(f"{alabel}asplit=2[vo][sc]")
                afilters.append("[mus][sc]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[duck]")
                afilters.append("[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[am]")
            else:
                afilters.append(f"{alabel}[mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[am]")
            alabel = "[am]"
    if cleanup is not None and cleanup.loudnorm:
        afilters.append(f"{alabel}loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[an]")
        alabel = "[an]"

    # 4) final pass
    out_name = "output.mp4"
    args = list(inputs)
    graph = vfilters + afilters
    if graph:
        args += ["-filter_complex", ";".join(graph)]
    args += ["-map", vlabel if vfilters else "0:v", "-map", alabel if afilters else "0:a"]
    args += (["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(fps)]
             if vfilters else ["-c:v", "copy"])
    args += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{T:.4f}", "-movflags", "+faststart", out_name]
    ctx.run_ffmpeg(args, expected_duration_s=T, pct_from=57, pct_to=97, step="final", cwd=str(rdir))

    # 5) verify against the time map (PRD §11.3 step 7)
    out_path = rdir / out_name
    info = probe(out_path)
    if not info["has_video"] or not info["has_audio"]:
        raise RuntimeError("Output में video/audio stream नहीं मिला।")
    if info["duration"] is None or abs(info["duration"] - T) > 0.1:
        raise RuntimeError(f"Output की लंबाई {info['duration']} s, अपेक्षित {T:.2f} s — रेंडर गलत है।")
    for f in rdir.iterdir():
        if f.name.startswith("seg_"):
            f.unlink(missing_ok=True)
    shutil.rmtree(rdir / "fonts", ignore_errors=True)

    asset = storage.add_asset(project_id, "output", out_path, "video/mp4", info["duration"],
                              {"name": f"edit-{rid}.mp4", "width": W, "height": H, "fps": fps, "plan_version": plan_version,
                               "expected_s": round(T, 3)},
                              attribution="; ".join(dict.fromkeys(attributions)) or None)
    applied = sorted({OP_LABEL[o.type] for o in plan.ops})
    return {"output_asset_id": asset["id"], "duration_s": info["duration"], "expected_s": round(T, 3),
            "source_s": D, "pieces": len(tm.pieces), "cuts": [[round(a, 3), round(b, 3)] for a, b in cuts],
            "caption_words": used_words, "notices": notices, "attributions": list(dict.fromkeys(attributions)),
            "applied": applied}


def timemap_for(project_id: str, plan: Plan) -> TimeMap | None:
    """Time map from explicit cuts/speed/zoom only (UI preview; silence cuts are known only at render)."""
    work = storage.latest_asset(project_id, "work")
    if work is None:
        return None
    ops = {t: [o for o in plan.ops if o.type == t] for t in ("speed", "zoom")}
    return build_timemap(float(work["duration_s"]), work["meta"]["fps"], merged_cuts(plan), ops["speed"], ops["zoom"])
