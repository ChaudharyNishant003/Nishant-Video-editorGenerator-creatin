"""Workflow B composition with ffmpeg (PRD §5.3 steps 6–8, §11.1, §11.5).

One ffmpeg process per scene: background or b-roll + avatar frames (raw RGBA on stdin) + optional side
insert + Devanagari ASS captions (+ brand watermark) + the scene's narration. Scene length is derived
from the measured narration audio (never from LLM guesses) and rounded to whole frames; segments are
H.264 + PCM in MKV (no AAC priming drift) and joined with the concat demuxer, then one final pass adds
music with ducking, loudnorm and AAC. Durations are verified and the render fails loudly on mismatch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from ..edit.captions import ass_text, ass_ts, build_scene_ass
from ..jobs import JobContext
from ..render.probe import probe
from . import avatar as av

FPS = 24
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
LAYOUTS = ("avatar_center_side_inserts", "broll_fullscreen_avatar_corner", "avatar_only")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


@dataclass
class Brand:
    """Optional brand kit (handoff extras): watermark logo + accent colour for captions/overlays."""
    logo: Path | None = None
    position: str = "top_left"      # top_left|top_right|bottom_left|bottom_right
    opacity: float = 0.8
    scale: float = 0.12             # logo width as a fraction of frame width
    accent: str | None = None       # "#RRGGBB" — caption highlight colour


@dataclass
class SceneSpec:
    sid: str
    layout: str
    audio: Path
    audio_dur: float
    words: list[dict]
    background: Path
    character: str
    outfit: str
    visual: Path | None = None
    caption_style: str | None = "hindi_bold_word_highlight"
    side: str = "right"
    seed: int = 0
    title: str | None = None        # optional on-screen heading (chapter start)
    brand: Brand = field(default_factory=Brand)


def frames_for(duration: float, fps: int = FPS) -> int:
    return max(1, int(math.ceil(duration * fps - 1e-6)))


def is_image(p: Path | None) -> bool:
    return p is not None and p.suffix.lower() in IMAGE_EXT


def geometry(layout: str, W: int, H: int) -> dict:
    """Pixel layout for one scene (avatar size/position, insert box)."""
    portrait, square = H > W, H == W
    g: dict = {"layout": layout}
    if layout == "broll_fullscreen_avatar_corner":
        ch = _even(H * (0.26 if portrait else 0.34 if square else 0.40))
        g["avatar"] = {"mode": "card", "height": ch, "x": None, "y": _even(H * 0.03), "margin": _even(W * 0.03)}
    else:
        frac = 0.66 if portrait else 0.88 if square else 0.97
        if layout == "avatar_center_side_inserts":
            frac = 0.60 if portrait else 0.80 if square else 0.97
        ah = _even(H * frac)
        g["avatar"] = {"mode": "full", "height": ah, "x": None, "y": H - int(ah * 0.95), "margin": 0}
    if layout == "avatar_center_side_inserts":
        if portrait:
            bw = _even(W * 0.86)
            g["insert"] = {"w": bw, "h": _even(bw * 9 / 16), "y": _even(H * 0.07), "x_left": _even((W - bw) / 2),
                           "x_right": _even((W - bw) / 2)}
        else:
            bw = _even(W * (0.40 if square else 0.30))
            g["insert"] = {"w": bw, "h": _even(bw * (1.0 if square else 0.75)), "y": _even(H * 0.10),
                           "x_left": _even(W * 0.03), "x_right": _even(W - bw - W * 0.03)}
    return g


def _ken_burns(label_in: str, W: int, H: int, n: int, seed: int, out: str) -> str:
    """Slow zoom on a pre-scaled still (pre-scaling to 1.25× output keeps zoompan cheap)."""
    PW, PH = _even(W * 1.25), _even(H * 1.25)
    zin = seed % 2 == 0
    step = 0.12 / max(1, n)
    z = f"min(1+{step:.6f}*on,1.12)" if zin else f"max(1.12-{step:.6f}*on,1.0)"
    fx = (0.5, 0.35, 0.65)[seed % 3]
    return (f"{label_in}scale={PW}:{PH}:force_original_aspect_ratio=increase,crop={PW}:{PH},setsar=1,"
            f"zoompan=z='{z}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*0.5':d=1:s={W}x{H}:fps={FPS},"
            f"trim=end_frame={n},setpts=PTS-STARTPTS{out}")


def _fit(label_in: str, W: int, H: int, n: int, out: str) -> str:
    return (f"{label_in}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
            f"tpad=stop_mode=clone:stop_duration=600,trim=end_frame={n},setpts=PTS-STARTPTS{out}")


def hex_to_bgr(color: str | None) -> str | None:
    """'#RRGGBB' → 'BBGGRR' for ASS colour tags; None if invalid."""
    c = (color or "").strip()
    if len(c) != 7 or not c.startswith("#") or any(ch not in "0123456789abcdefABCDEF" for ch in c[1:]):
        return None
    return (c[5:7] + c[3:5] + c[1:3]).upper()


def scene_command(spec: SceneSpec, W: int, H: int, font_family: str, workdir: Path, out_name: str):
    """Returns (ffmpeg args, avatar frame iterator, frame count, scene duration)."""
    n = frames_for(spec.audio_dur)
    D = n / FPS
    g = geometry(spec.layout, W, H)
    a = g["avatar"]
    card_bg = str(spec.background) if a["mode"] == "card" else None
    sprites = av.build_sprites(spec.character, spec.outfit, a["mode"], a["height"], card_bg)
    if a["mode"] == "card":
        ax = W - sprites.width - a["margin"]
        ay = a["y"]
    else:
        ax = (W - sprites.width) // 2
        ay = a["y"]
    levels, blinks, sways = av.frame_tracks(spec.audio, FPS, n, spec.seed)

    inputs: list[str] = []
    graph: list[str] = []
    # 0: base picture
    base_is_broll = spec.layout == "broll_fullscreen_avatar_corner" and spec.visual is not None
    base_src = spec.visual if base_is_broll else spec.background
    if is_image(base_src):
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D + 1:.3f}", "-i", str(base_src)]
        if base_is_broll:
            graph.append(_ken_burns("[0:v]", W, H, n, spec.seed, "[base]"))
        else:
            graph.append(_fit("[0:v]", W, H, n, "[base]"))
    else:
        inputs += ["-stream_loop", "-1", "-t", f"{D + 1:.3f}", "-i", str(base_src)]
        graph.append(_fit("[0:v]", W, H, n, "[base]"))
    # 1: avatar frames from stdin
    inputs += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{sprites.width}x{sprites.height}",
               "-framerate", str(FPS), "-i", "pipe:0"]
    # 2: narration
    inputs += ["-i", str(spec.audio)]
    k = 3
    vlabel = "[base]"
    if spec.layout == "avatar_center_side_inserts" and spec.visual is not None:
        ins = g["insert"]
        bw, bh = ins["w"], ins["h"]
        border = max(4, bw // 80)
        if is_image(spec.visual):
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D + 1:.3f}", "-i", str(spec.visual)]
        else:
            inputs += ["-stream_loop", "-1", "-t", f"{D + 1:.3f}", "-i", str(spec.visual)]
        fade_in, fade_out = min(0.25, D / 4), max(0.0, D - 0.55)
        graph.append(f"[{k}:v]scale={bw - 2 * border}:{bh - 2 * border}:force_original_aspect_ratio=increase,"
                     f"crop={bw - 2 * border}:{bh - 2 * border},setsar=1,fps={FPS},"
                     f"pad={bw}:{bh}:{border}:{border}:white,format=rgba,"
                     f"tpad=stop_mode=clone:stop_duration=600,trim=end_frame={n},setpts=PTS-STARTPTS,"
                     f"fade=t=in:st={fade_in:.3f}:d=0.35:alpha=1,fade=t=out:st={fade_out:.3f}:d=0.4:alpha=1[ins]")
        x = ins["x_left"] if spec.side == "left" else ins["x_right"]
        graph.append(f"{vlabel}[ins]overlay=x={x}:y={ins['y']}:format=auto[v{k}]")
        vlabel = f"[v{k}]"
        k += 1
        if H <= W:  # landscape/square: keep the avatar clear of the insert
            shift = int(W * 0.12) * (1 if spec.side == "left" else -1)
            ax = max(0, min(W - sprites.width, ax + shift))
    graph.append(f"[1:v]format=rgba,setpts=PTS-STARTPTS[av]")
    graph.append(f"{vlabel}[av]overlay=x={ax}:y={ay}:format=auto:eof_action=repeat[va]")
    vlabel = "[va]"

    brand = spec.brand
    if brand.logo is not None and Path(brand.logo).is_file():
        lw = _even(W * max(0.04, min(0.3, brand.scale)))
        m = _even(W * 0.025)
        pos = {"top_left": (f"{m}", f"{m}"), "top_right": (f"W-w-{m}", f"{m}"),
               "bottom_left": (f"{m}", f"H-h-{m}"), "bottom_right": (f"W-w-{m}", f"H-h-{m}")}
        px, py = pos.get(brand.position, pos["top_left"])
        if spec.layout == "broll_fullscreen_avatar_corner" and brand.position == "top_right":
            px, py = pos["top_left"]  # never under the avatar card
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D + 1:.3f}", "-i", str(brand.logo)]
        graph.append(f"[{k}:v]scale={lw}:-2,format=rgba,colorchannelmixer=aa={max(0.1, min(1.0, brand.opacity)):.2f}[logo]")
        graph.append(f"{vlabel}[logo]overlay=x={px}:y={py}:shortest=0:eof_action=repeat[vl]")
        vlabel = "[vl]"
        k += 1

    extra = []
    if spec.title:
        ty = _even(H * 0.04)
        if "insert" in g and H > W:  # portrait: insert sits on top — heading goes just below it
            ty = g["insert"]["y"] + g["insert"]["h"] + _even(H * 0.015)
        extra.append(f"Dialogue: 2,{ass_ts(0.1)},{ass_ts(min(D, 3.2))},white_box,,0,0,0,,"
                     f"{{\\an8\\pos({W // 2},{ty})}}{ass_text(spec.title)}")
    if spec.caption_style or extra:
        ass = build_scene_ass(font_family, W, H, spec.words, spec.caption_style, extra)
        bgr = hex_to_bgr(brand.accent)
        if bgr:  # brand accent colour for the highlighted word
            ass = ass.replace("{\\c&H00FFFF&}", "{\\c&H" + bgr + "&}")
        (workdir / f"subs_{spec.sid}.ass").write_text(ass, encoding="utf-8")
        graph.append(f"{vlabel}ass=filename=subs_{spec.sid}.ass:fontsdir=fonts:shaping=complex[vs]")
        vlabel = "[vs]"
    graph.append(f"{vlabel}format=yuv420p,setsar=1[vout]")
    graph.append(f"[2:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={D:.6f},"
                 f"atrim=end={D:.6f},asetpts=PTS-STARTPTS[aout]")
    args = [*inputs, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
            "-frames:v", str(n), "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-g", str(FPS * 2), "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            "-t", f"{D:.6f}", out_name]
    return args, sprites.frames(levels, blinks, sways), n, D


def render_scene(ctx: JobContext, spec: SceneSpec, aspect: str, font_family: str, workdir: Path,
                 pct_from: float, pct_to: float, step: str) -> tuple[Path, float]:
    W, H = SIZES[aspect]
    out_name = f"scene_{spec.sid}.mkv"
    tmp_name = f"scene_{spec.sid}.part.mkv"
    args, frames, n, D = scene_command(spec, W, H, font_family, workdir, tmp_name)
    ctx.run_ffmpeg(args, expected_duration_s=D, pct_from=pct_from, pct_to=pct_to, step=step, cwd=str(workdir),
                   stdin_frames=frames)
    tmp = workdir / tmp_name
    info = probe(tmp)
    if info["duration"] is None or abs(info["duration"] - D) > 1.5 / FPS:
        raise RuntimeError(f"सीन {spec.sid}: लंबाई {info['duration']} s, अपेक्षित {D:.3f} s — रेंडर गलत है।")
    final = workdir / out_name
    tmp.replace(final)
    return final, D


def finish_video(ctx: JobContext, workdir: Path, segments: list[Path], durations: list[float], out_path: Path,
                 music: Path | None = None, music_volume: float = 0.12, intro: Path | None = None,
                 outro: Path | None = None, aspect: str = "16:9", pct_from: float = 85, pct_to: float = 98) -> float:
    """Concat scene segments (+ optional intro/outro clips) → final MP4 with music ducking + loudnorm.
    Returns the verified duration."""
    W, H = SIZES[aspect]
    names = [s.name for s in segments]
    extra_total = 0.0
    for tag, clip in (("intro", intro), ("outro", outro)):
        if clip is None:
            continue
        info = probe(clip)
        dur = min(float(info["duration"] or 0), 30.0)
        if dur <= 0.2:
            continue
        nf = frames_for(dur)
        d = nf / FPS
        name = f"{tag}.mkv"
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
              f"fps={FPS},tpad=stop_mode=clone:stop_duration=5,trim=end_frame={nf},setpts=PTS-STARTPTS,format=yuv420p")
        a_in = ["-i", str(clip)] if info["has_audio"] else ["-i", str(clip), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        a_map = "0:a:0" if info["has_audio"] else "1:a:0"
        ctx.run_ffmpeg([*a_in, "-map", "0:v:0", "-map", a_map, "-vf", vf,
                        "-af", f"aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={d:.6f},atrim=end={d:.6f}",
                        "-frames:v", str(nf), "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                        "-g", str(FPS * 2), "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
                        "-t", f"{d:.6f}", name], step=tag, cwd=str(workdir))
        if tag == "intro":
            names.insert(0, name)
        else:
            names.append(name)
        extra_total += d
    (workdir / "segments.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
    T = sum(durations) + extra_total
    inputs = ["-f", "concat", "-safe", "0", "-i", "segments.txt"]
    af: list[str] = []
    alabel = "[0:a]"
    if music is not None:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        af.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={T:.3f},volume={music_volume:.3f},"
                  f"afade=t=in:d=1,afade=t=out:st={max(0.0, T - 2):.3f}:d=2[mus]")
        af.append(f"{alabel}asplit=2[vo][sc]")
        af.append("[mus][sc]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[duck]")
        af.append("[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[am]")
        alabel = "[am]"
    af.append(f"{alabel}loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    tmp = out_path.with_suffix(".part.mp4")
    ctx.run_ffmpeg([*inputs, "-filter_complex", ";".join(af), "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{T:.4f}",
                    "-movflags", "+faststart", tmp.name], expected_duration_s=T, pct_from=pct_from, pct_to=pct_to,
                   step="final", cwd=str(workdir))
    info = probe(tmp)
    if not info["has_video"] or not info["has_audio"]:
        raise RuntimeError("Output में video/audio stream नहीं मिला।")
    if info["duration"] is None or abs(info["duration"] - T) > 0.1:
        raise RuntimeError(f"Output की लंबाई {info['duration']} s, अपेक्षित {T:.2f} s — रेंडर गलत है।")
    tmp.replace(out_path)
    return float(info["duration"])
