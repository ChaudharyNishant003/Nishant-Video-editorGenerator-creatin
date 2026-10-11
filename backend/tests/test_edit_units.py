"""Workflow A units: plan validation, time map, ASS captions, LLM plan repair/fallback, upload/API guards."""

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.edit import pipeline, planner
from app.edit.captions import ass_text, build_ass, remap_words
from app.edit.plan import PlanTooShort, merged_cuts, parse_time, validate_plan
from app.edit.timemap import build_timemap
from app.providers import registry
from app.render.ffmpeg import ffmpeg_exe
from app.render.fonts import stage_fonts
from app.security.keys import encode_keys_header


# --- plan validation -----------------------------------------------------------------------------
def test_parse_time_formats():
    assert parse_time(65) == 65.0
    assert parse_time("1:05") == 65.0
    assert parse_time("1:05.5") == 65.5
    assert parse_time("0:01:05") == 65.0
    assert parse_time("12.5s") == 12.5
    with pytest.raises(ValueError):
        parse_time("थोड़ी देर बाद")


def test_timestamp_past_end_is_a_warning_not_a_failure():
    plan = validate_plan({"ops": [{"type": "cut", "start": "0:30", "end": "0:35"}]}, 34.0)
    assert (plan.ops[0].start, plan.ops[0].end) == (30.0, 34.0)
    assert any("सीमित" in w for w in plan.warnings)


def test_bad_ops_are_dropped_with_warnings():
    plan = validate_plan({"ops": [
        {"type": "cut", "start": 10, "end": 5},            # start >= end
        {"type": "explode", "start": 1, "end": 2},         # unknown type
        {"type": "zoom", "start": 1, "end": 3, "scale": 5},  # clamped
        {"type": "speed", "start": 4, "end": 6, "factor": 1.0},  # no-op
        {"type": "text_overlay", "start": 1, "end": 2, "text": "  "},
        {"type": "broll", "start": 1, "end": 2, "source": "http://evil"},
        "nonsense",
    ], "question": "कौन सा हिस्सा?"}, 60.0)
    assert [o.type for o in plan.ops] == ["zoom"]
    assert plan.ops[0].scale == 2.0
    assert plan.question == "कौन सा हिस्सा?"
    assert len(plan.warnings) >= 6


def test_overlapping_cuts_merge_and_conflicts_resolve():
    plan = validate_plan({"ops": [
        {"type": "cut", "start": 10, "end": 20}, {"type": "cut", "start": 15, "end": 25},
        {"type": "zoom", "start": 30, "end": 40}, {"type": "zoom", "start": 35, "end": 45},
        {"type": "captions"}, {"type": "captions", "style": "line"},
    ]}, 60.0)
    assert merged_cuts(plan) == [(10.0, 25.0)]
    assert len([o for o in plan.ops if o.type == "zoom"]) == 1
    assert len([o for o in plan.ops if o.type == "captions"]) == 1
    assert any("जोड़" in w for w in plan.warnings)


def test_cutting_everything_is_refused():
    with pytest.raises(PlanTooShort):
        validate_plan({"ops": [{"type": "cut", "start": 0, "end": 60}]}, 60.0)


def test_music_and_broll_must_reference_project_uploads():
    plan = validate_plan({"ops": [{"type": "music", "track": "upload:abc"},
                                  {"type": "broll", "start": 1, "end": 2, "source": "upload:zzz"},
                                  {"type": "broll", "start": 3, "end": 4, "source": "stock:  city traffic "}]},
                         60.0, asset_ids={"abc"})
    assert [o.type for o in plan.ops] == ["music", "broll"]
    assert plan.ops[1].source == "stock:city traffic"


# --- time map ------------------------------------------------------------------------------------
def test_timemap_cut_and_speed():
    plan = validate_plan({"ops": [{"type": "cut", "start": 12, "end": 18},
                                  {"type": "speed", "start": 30, "end": 40, "factor": 2}]}, 60.0)
    speeds = [o for o in plan.ops if o.type == "speed"]
    tm = build_timemap(60.0, 30, merged_cuts(plan), speeds, [])
    assert abs(tm.total - (60 - 6 - 5)) < 1e-6
    assert tm.map_time(15) is None
    assert abs(tm.map_time(20) - 14) < 1e-6
    assert abs(tm.map_time(35) - 26.5) < 1e-6          # 24 + 5/2
    assert abs(tm.map_time(50) - 39) < 1e-6
    assert tm.map_range(10, 20) == [(10.0, pytest.approx(14.0))]
    assert len(tm.map_range(5, 25)) == 1                # cut collapses into one continuous output range


def test_timemap_is_frame_aligned():
    tm = build_timemap(10.0, 30, [(1.234, 2.345)], [], [])
    for p in tm.pieces:
        assert abs(p.src_start * 30 - round(p.src_start * 30)) < 1e-6
        assert abs(p.out_start * 30 - round(p.out_start * 30)) < 1e-6


# --- captions ------------------------------------------------------------------------------------
def test_ass_text_neutralises_override_tags():
    assert ass_text("{\\pos(1,1)}hi\nthere") == "(＼pos(1,1))hi\\Nthere"


def test_caption_words_follow_cuts():
    tm = build_timemap(20.0, 30, [(5, 10)], [], [])
    words = [{"text": "पहला", "start": 1, "end": 2}, {"text": "कटा", "start": 6, "end": 7},
             {"text": "बाद", "start": 11, "end": 12}]
    out = remap_words(words, tm)
    assert [w["text"] for w in out] == ["पहला", "बाद"]
    assert abs(out[1]["start"] - 6) < 1e-6
    ass, used = build_ass("Nirmala UI", 1280, 720, tm, words,
                          validate_plan({"ops": [{"type": "captions"}]}, 20).ops[0], [])
    assert used == 2 and "कटा" not in ass and "PlayResX: 1280" in ass


def _ink_width(ass_body: str, shaping: str, tmp: Path) -> int:
    family = stage_fonts(tmp / "fonts")
    (tmp / "t.ass").write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 800", "PlayResY: 200", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: D,{family},120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:00:01.00,D,,0,0,0,,{ass_body}"]) + "\n", encoding="utf-8")
    raw = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=800x200:d=1",
                          "-vf", f"ass=filename=t.ass:fontsdir=fonts:shaping={shaping}", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], cwd=tmp, capture_output=True, check=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(200, 800)
    cols = np.where(img.max(axis=0) > 100)[0]
    return int(cols.max() - cols.min())


def test_devanagari_conjuncts_are_shaped(tmp_path):
    """Regression for the `subtitles` vs `ass` filter pitfall: complex shaping must form the conjunct
    (क्ष as one glyph), which is clearly narrower than the unshaped क + halant + ष."""
    shaped = _ink_width("क्ष", "complex", tmp_path)
    unshaped = _ink_width("क्ष", "simple", tmp_path)
    assert shaped < unshaped * 0.8, (shaped, unshaped)


def test_renderer_uses_complex_shaping():
    src = Path(pipeline.__file__).read_text(encoding="utf-8")
    assert "ass=filename=subs.ass:fontsdir=fonts:shaping=complex" in src
    assert "subtitles=filename" not in src


# --- LLM plan: repair + fallback (mocked providers) ----------------------------------------------
GOOD = json.dumps({"version": 1, "ops": [{"type": "cut", "start": "0:12", "end": 18},
                                          {"type": "captions", "style": "hindi_bold_word_highlight"}],
                   "warnings": [], "question": None})


@pytest.fixture()
def fake_llms(monkeypatch):
    calls = []

    def make(name, replies):
        def impl(system, user, keys, json_mode=False, model=None):
            calls.append(name)
            return replies.pop(0) if replies else "still not json"
        return impl

    def install(groq_replies, gemini_replies):
        monkeypatch.setattr(registry.get("groq"), "impl", make("groq", list(groq_replies)))
        monkeypatch.setattr(registry.get("gemini"), "impl", make("gemini", list(gemini_replies)))
        return calls
    return install


KEYS = {"groq": {"apiKey": "gsk_fake"}, "gemini": {"apiKey": "fake"}}


def test_llm_invalid_json_is_repaired_on_same_provider(fake_llms):
    calls = fake_llms(["```json\n{oops", GOOD], [])
    notes = []
    plan, label = planner.make_plan("12 से 18 सेकंड काटो और कैप्शन लगाओ", 60.0, [], [], KEYS, "groq", notes.append)
    assert label == "Groq" and calls == ["groq", "groq"]
    assert [o.type for o in plan.ops] == ["cut", "captions"] and plan.ops[0].start == 12.0
    assert any("सुधार" in n for n in notes)


def test_llm_garbage_twice_falls_back_to_next_free_llm(fake_llms):
    calls = fake_llms(["nope", "still nope"], ["Here you go: " + GOOD + " hope it helps"])
    notes = []
    plan, label = planner.make_plan("कट करो", 60.0, None, [], KEYS, "groq", notes.append)
    assert label == "Google Gemini" and calls == ["groq", "groq", "gemini"]
    assert any("switch" in n for n in notes)
    assert len(plan.ops) == 2


def test_llm_all_fail_gives_clear_error(fake_llms):
    fake_llms(["x", "y"], ["z", "w"])
    with pytest.raises(Exception) as e:
        planner.make_plan("कट करो", 60.0, None, [], KEYS, "groq", lambda m: None)
    assert getattr(e.value, "kind", "") == "all_failed"


def test_plan_endpoint_without_llm_key_explains(authed, tmp_path):
    pid = _ingested_project(authed, tmp_path)
    r = authed.post(f"/api/projects/{pid}/plan", json={"prompt": "पहले 5 सेकंड काटो"})
    assert r.status_code == 502 and "Settings" in r.json()["error"]["message"]


def test_plan_endpoint_with_mocked_llm(authed, tmp_path, fake_llms):
    fake_llms([GOOD], [])
    pid = _ingested_project(authed, tmp_path)
    hdr = {"X-Provider-Keys": encode_keys_header({"groq": {"apiKey": "gsk_fake"}})}
    r = authed.post(f"/api/projects/{pid}/plan", json={"prompt": "12 से 18 काटो"}, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "Groq" and body["plan"]["version"] == 1
    # the clip is 8 s long: cut 12–18 is past the end → dropped with a warning, captions kept
    assert [o["type"] for o in body["plan"]["plan"]["ops"]] == ["captions"]
    assert body["plan"]["plan"]["warnings"]


# --- upload / API guards -------------------------------------------------------------------------
def _clip(path: Path, seconds: float = 8, audio: bool = True, size: str = "320x240") -> Path:
    args = [ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=25:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=300:d={seconds}"]
    subprocess.run(args + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _wait(client, job_id):
    import time
    for _ in range(600):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.2)
    raise AssertionError("timeout")


def _ingested_project(client, tmp_path, **kw) -> str:
    pid = client.post("/api/projects", json={"kind": "edit"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/upload?kind=source&name=clip.mp4", content=_clip(tmp_path / "c.mp4", **kw).read_bytes())
    assert r.status_code == 200, r.text
    assert _wait(client, r.json()["job_id"])["status"] == "done"
    return pid


def test_upload_rejects_bad_files(authed, tmp_path, monkeypatch):
    pid = authed.post("/api/projects", json={"kind": "edit"}).json()["id"]
    r = authed.post(f"/api/projects/{pid}/upload?kind=source&name=a.exe", content=b"MZ")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_type"
    r = authed.post(f"/api/projects/{pid}/upload?kind=source&name=a.mp4", content=b"not a video at all")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_media"
    import dataclasses

    from app.edit import routes
    monkeypatch.setattr(routes, "settings", dataclasses.replace(routes.settings, max_upload_seconds=5))
    long_clip = _clip(tmp_path / "long.mp4", seconds=8)
    r = authed.post(f"/api/projects/{pid}/upload?kind=source&name=long.mp4", content=long_clip.read_bytes())
    assert r.status_code == 400 and "सीमा" in r.json()["error"]["message"]
    # nothing half-written is left behind, so a retry works
    assert not list((Path(routes.settings.data_dir) / "projects" / pid).glob("*.part"))


def test_video_without_audio_gets_silent_track_and_skips_stt(authed, tmp_path):
    pid = _ingested_project(authed, tmp_path, audio=False)
    j = _wait(authed, authed.post(f"/api/projects/{pid}/transcribe", json={}).json()["job_id"])
    assert j["status"] == "done" and j["result"]["words"] == 0
    st = authed.get(f"/api/projects/{pid}/state").json()
    assert st["work"]["meta"]["source_has_audio"] is False and st["transcript"]["word_count"] == 0


def test_transcribe_without_key_fails_clearly(authed, tmp_path):
    pid = _ingested_project(authed, tmp_path)
    j = _wait(authed, authed.post(f"/api/projects/{pid}/transcribe", json={}).json()["job_id"])
    assert j["status"] == "failed" and "key" in j["error"]


def test_portrait_video_keeps_aspect(authed, tmp_path):
    pid = _ingested_project(authed, tmp_path, size="1080x1920", seconds=2)
    w = authed.get(f"/api/projects/{pid}/state").json()["work"]["meta"]
    assert (w["width"], w["height"]) == (720, 1280)


def test_assets_need_login_and_support_range(authed, client, tmp_path):
    pid = _ingested_project(authed, tmp_path)
    url = authed.get(f"/api/projects/{pid}/state").json()["work"]["url"]
    r = authed.get(url, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    authed.post("/api/auth/logout")
    assert authed.get(url).status_code == 401


def test_render_needs_a_plan_and_cant_cut_everything(authed, tmp_path):
    pid = _ingested_project(authed, tmp_path)
    assert authed.post(f"/api/projects/{pid}/approve-and-render").status_code == 400
    r = authed.put(f"/api/projects/{pid}/plan", json={"plan": {"ops": [{"type": "cut", "start": 0, "end": 99}]}})
    assert r.status_code == 422
    r = authed.put(f"/api/projects/{pid}/plan", json={"plan": {"ops": [{"type": "cut", "start": 1, "end": 2}]}})
    assert r.status_code == 200 and r.json()["plan"]["expected_duration_s"] == 7.0


def test_delete_project_removes_its_media(authed, tmp_path):
    pid = _ingested_project(authed, tmp_path)
    from app.config import settings
    d = settings.data_dir / "projects" / pid
    assert (d / "work.mp4").exists()
    assert authed.delete(f"/api/projects/{pid}").status_code == 200
    assert not d.exists()
