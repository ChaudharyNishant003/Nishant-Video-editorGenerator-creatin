"""Workflow B rendering + end-to-end (PRD §14 Workflow B).

Offline: scripted LLM, tone-based fake TTS (word timings known), synthetic images. Real Edge-TTS is covered
by test_providers (network). 3-minute runs are slow on this laptop and run when AIYT_SLOW=1 (acceptance run).
"""

import logging
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
import requests

from app.create import avatar as av
from app.create import compose, visuals
from app.jobs import JobContext
from app.providers import registry
from app.render.ffmpeg import ffmpeg_exe
from app.render.fonts import stage_fonts
from app.render.probe import probe
from app.security.keys import encode_keys_header
from create_fixtures import fake_image, fake_tts, scripted_llm

ARTIFACTS = Path(os.environ.get("AIYT_TEST_ARTIFACTS", Path(__file__).resolve().parent / ".artifacts"))
SLOW = os.environ.get("AIYT_SLOW") == "1"
KEYS = {"groq": {"apiKey": "gsk_test_key_123"}}
HDR = {"X-Provider-Keys": encode_keys_header(KEYS)}


def _ctx(data_dir) -> JobContext:
    from app import db

    jid = db.new_id()
    with db.locked() as c:
        c.execute("INSERT INTO jobs(id, kind, status, progress, log_json, created_at) VALUES (?,?,?,?,?,?)",
                  (jid, "test", "running", 0, "[]", time.time()))
    return JobContext(jid, {})


def _tone_audio(path: Path, pattern_s: float = 1.0, dur: float = 6.0) -> Path:
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='0.6*sin(2*PI*300*t)*lt(mod(t,{2 * pattern_s}),{pattern_s})':s=24000:d={dur}",
                    "-c:a", "libmp3lame", str(path)], check=True)
    return path


def _crop_frames(video: Path, x: int, y: int, w: int, h: int) -> np.ndarray:
    raw = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(video), "-vf", f"crop={w}:{h}:{x}:{y}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w)


@pytest.fixture()
def offline(monkeypatch):
    tts_calls, img_calls = [], []
    monkeypatch.setattr(registry.get("edge_tts"), "impl", fake_tts(tts_calls))
    monkeypatch.setattr(registry.get("groq"), "impl", scripted_llm())
    monkeypatch.setattr(visuals, "pollinations_generate", fake_image(img_calls))
    monkeypatch.setattr(registry.get("wikimedia"), "impl", lambda q, k, **kw: [])
    return {"tts": tts_calls, "img": img_calls}


# --- avatar: mouth follows speech, blinks, no frozen frames -------------------------------------------
def test_avatar_mouth_follows_speech_blinks_and_never_freezes(data_dir, tmp_path):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    audio = _tone_audio(tmp_path / "tone.mp3")            # loud 0–1 s, silent 1–2 s, …
    dur = probe(audio)["duration"]
    work = tmp_path / "r"
    work.mkdir()
    font = stage_fonts(work / "fonts")
    W, H = compose.SIZES["16:9"]
    spec = compose.SceneSpec(sid="m", layout="avatar_only", audio=audio, audio_dur=dur, words=[],
                             background=av.background_path("studio", "16:9"), character="aarav", outfit="blue",
                             caption_style=None, seed=5)
    out, D = compose.render_scene(_ctx(data_dir), spec, "16:9", font, work, 0, 100, "t")
    n = compose.frames_for(dur)
    assert abs(D - n / compose.FPS) < 1e-9

    g = compose.geometry("avatar_only", W, H)
    sp = av.build_sprites("aarav", "blue", "full", g["avatar"]["height"])
    s = sp.height / 1300
    ax, ay = (W - sp.width) // 2, g["avatar"]["y"]
    mx, my = int(ax + 500 * s), int(ay + 412 * s)
    mouth = _crop_frames(out, mx - int(40 * s), my - int(30 * s), int(80 * s) // 2 * 2, int(60 * s) // 2 * 2)
    assert mouth.shape[0] == n                             # frame count = duration × fps
    dark = (mouth < 110).mean(axis=(1, 2))                 # open mouth = dark inner area
    fps = compose.FPS
    loud = [dark[i] for i in range(n) if 0.25 < (i / fps) % 2.0 < 0.8]
    quiet = [dark[i] for i in range(n) if 1.3 < (i / fps) % 2.0 < 1.85]
    assert np.mean(loud) > np.mean(quiet) * 3 and np.mean(loud) > 0.08, (np.mean(loud), np.mean(quiet))

    ex, ey = int(ax + 452 * s), int(ay + 318 * s)
    eyes = _crop_frames(out, ex - int(30 * s), ey - int(20 * s), int(60 * s) // 2 * 2, int(40 * s) // 2 * 2).astype(float)
    blinks = av.blink_track(n, fps, 5)
    bright = eyes.mean(axis=(1, 2))
    assert any(blinks) and abs(np.mean(bright[np.array(blinks)]) - np.mean(bright[~np.array(blinks)])) > 10

    md5 = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(out), "-f", "framemd5", "-"],
                         capture_output=True, text=True, check=True).stdout
    hashes = [ln.split(",")[-1].strip() for ln in md5.splitlines() if ln and not ln.startswith("#") and ln.startswith("0,")]
    for i in range(0, len(hashes) - fps, fps):
        assert len(set(hashes[i:i + fps])) > 1, f"frozen second at frame {i}"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-ss", "0.5", "-i", str(out), "-frames:v", "1",
                    str(ARTIFACTS / "create_mouth_open.png")], check=True)


# --- every layout × aspect: exact scene durations ------------------------------------------------------
@pytest.mark.parametrize("aspect", ["16:9", "9:16", "1:1"])
def test_layouts_render_with_exact_durations(data_dir, tmp_path, aspect):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    audio = tmp_path / "a.mp3"
    res = fake_tts()("क्षत्रिय श्रीमान द्वारा कर्मचारियों का स्वागत हुआ।", {}, audio)
    dur = probe(audio)["duration"] + 0.35
    img = tmp_path / "v.jpg"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=800x600", "-frames:v", "1", str(img)], check=True)
    work = tmp_path / "r"
    work.mkdir()
    font = stage_fonts(work / "fonts")
    W, H = compose.SIZES[aspect]
    for i, layout in enumerate(compose.LAYOUTS):
        spec = compose.SceneSpec(sid=f"s{i}", layout=layout, audio=audio, audio_dur=dur, words=res["words"],
                                 background=av.background_path("library", aspect), character=["aarav", "meera", "dadaji"][i],
                                 outfit="mustard", visual=img, side="left", seed=i, title="अध्याय" if i == 0 else None)
        out, D = compose.render_scene(_ctx(data_dir), spec, aspect, font, work, 0, 100, "t")
        info = probe(out)
        assert (info["width"], info["height"]) == (W, H)
        assert abs(info["duration"] - compose.frames_for(dur) / compose.FPS) <= 1.0 / compose.FPS
        tag = aspect.replace(":", "x")
        subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-ss", "1.2", "-i", str(out), "-frames:v", "1",
                        str(ARTIFACTS / f"create_{tag}_{layout}.png")], check=True)


# --- end to end through the API ----------------------------------------------------------------------
def _wait(client, jid, timeout=1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.3)
    raise AssertionError("job timeout")


def _make(authed, minutes, aspect, **extra):
    pid = authed.post("/api/projects", json={"kind": "create"}).json()["id"]
    r = authed.put(f"/api/projects/{pid}/settings", json={"wizard": {"topic": "रायगढ़ किला", "minutes": minutes,
                                                                      "aspect": aspect, "character": "meera", **extra}})
    assert r.status_code == 200, r.text
    return pid


def _run_full(authed, minutes, aspect):
    pid = _make(authed, minutes, aspect)
    assert authed.post(f"/api/projects/{pid}/research", headers={}).status_code == 400      # no LLM key → clear error
    j = _wait(authed, authed.post(f"/api/projects/{pid}/script", json={}, headers=HDR).json()["job_id"])
    assert j["status"] == "done", j
    t0 = time.time()
    g = _wait(authed, authed.post(f"/api/projects/{pid}/generate", json={}, headers=HDR).json()["job_id"])
    took = time.time() - t0
    assert g["status"] == "done", g
    st = authed.get(f"/api/projects/{pid}/create-state").json()
    return pid, g, st, took


def _check_run(authed, pid, g, st, minutes, aspect):
    res = g["result"]
    W, H = compose.SIZES[aspect]
    out = st["outputs"][0]
    assert (out["meta"]["width"], out["meta"]["height"]) == (W, H)
    # scene durations come from real audio: each = audio(+pad) rounded up to whole frames; total = sum
    scenes = st["scenes"]
    expect = sum(compose.frames_for(s["duration"]) / compose.FPS for s in scenes.values())
    assert abs(res["duration_s"] - expect) <= 0.1 and abs(res["expected_s"] - expect) < 1e-3
    assert 0.5 * minutes * 60 <= res["duration_s"] <= 1.6 * minutes * 60, res["duration_s"]
    assert len(set(res["layouts"].values())) >= 2
    meta = st["meta"]
    assert len(meta["titles"]) == 3 and meta["youtube_description"].count("\n") >= 2
    assert [c["t"] for c in meta["chapters"]] == sorted(c["t"] for c in meta["chapters"]) and meta["chapters"][0]["t"] == 0
    assert st["thumbnail"] and "Pollinations" in (out["attribution"] or "")
    return res


def test_one_minute_runs_16x9_and_9x16(authed, offline):
    for aspect in ("16:9", "9:16"):
        pid, g, st, took = _run_full(authed, 1, aspect)
        _check_run(authed, pid, g, st, 1, aspect)
        out = st["outputs"][0]
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        r = authed.get(f"{out['url']}?download=1")
        assert r.status_code == 403 and r.json()["error"]["code"] == "disclosure_required"
        assert authed.get(f"/api/projects/{pid}/youtube-pack.txt").status_code == 403
        assert authed.post(f"/api/projects/{pid}/disclosure", json={"ack": True, "checklist": [True, False, True, True]}).status_code == 400
        assert authed.post(f"/api/projects/{pid}/disclosure", json={"ack": True, "checklist": [True] * 4}).status_code == 200
        r = authed.get(f"{out['url']}?download=1")
        assert r.status_code == 200 and len(r.content) > 10_000
        pk = authed.get(f"/api/projects/{pid}/youtube-pack.txt")
        assert pk.status_code == 200 and "AI" in pk.text and ("0:00" in pk.text) == (len(st["meta"]["chapters"]) >= 2)
        assert authed.get(f"/api/projects/{pid}/youtube-pack.txt?platform=instagram").status_code == 200
        (ARTIFACTS / f"create_e2e_{aspect.replace(':', 'x')}.mp4").write_bytes(r.content)
        logging.getLogger("test").info("1-min %s generate took %.1f s", aspect, took)


def test_resume_after_cancel_and_regenerate_one_scene(authed, offline, data_dir):
    pid = _make(authed, 1, "16:9", layout="avatar_center_side_inserts")
    assert _wait(authed, authed.post(f"/api/projects/{pid}/script", json={}, headers=HDR).json()["job_id"])["status"] == "done"
    jid = authed.post(f"/api/projects/{pid}/generate", json={}, headers=HDR).json()["job_id"]
    for _ in range(600):  # cancel once scene rendering has started
        j = authed.get(f"/api/jobs/{jid}").json()
        if (j["step"] or "").startswith("scene 2") or j["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    authed.post(f"/api/jobs/{jid}/cancel")
    assert _wait(authed, jid)["status"] == "cancelled"
    n_tts = len(offline["tts"])
    g = _wait(authed, authed.post(f"/api/projects/{pid}/generate", json={}, headers=HDR).json()["job_id"])
    assert g["status"] == "done", g
    assert len(offline["tts"]) == n_tts, "resume must reuse cached narration"
    log = " ".join(x["msg"] for x in g["log"])
    assert "वीडियो तैयार" in log
    render = data_dir / "projects" / pid / "create" / "render"
    before = {p.name: p.stat().st_mtime_ns for p in render.glob("scene_*.mkv")}
    # regenerate scene c1s1 visual → only that scene is re-rendered
    st = authed.get(f"/api/projects/{pid}/create-state").json()
    first = st["script"]["chapters"][0]["scenes"][0]["id"]
    r = _wait(authed, authed.post(f"/api/projects/{pid}/scenes/{first}/regenerate", json={"what": "visual", "query": "new fort view"},
                                  headers=HDR).json()["job_id"])
    assert r["status"] == "done", r
    after = {p.name: p.stat().st_mtime_ns for p in render.glob("scene_*.mkv")}
    changed = [k for k in before if after.get(k) != before[k]]
    assert changed == [f"scene_{first}.mkv"], changed
    st2 = authed.get(f"/api/projects/{pid}/create-state").json()
    assert st2["script"]["chapters"][0]["scenes"][0]["visual"]["query"] == "new fort view"
    assert len(st2["outputs"]) == 2 and abs(st2["outputs"][0]["duration_s"] - g["result"]["duration_s"]) < 0.1
    # text regenerate via LLM rewrite changes narration → new voice for that scene only
    n_tts = len(offline["tts"])
    r = _wait(authed, authed.post(f"/api/projects/{pid}/scenes/{first}/regenerate", json={"what": "text"}, headers=HDR).json()["job_id"])
    assert r["status"] == "done" and len(offline["tts"]) == n_tts + 1


def test_manual_script_without_any_key(authed, offline):
    pid = _make(authed, 1, "1:1", caption_script="roman")
    assert authed.post(f"/api/projects/{pid}/script", json={}).status_code == 400          # no LLM key
    r = authed.put(f"/api/projects/{pid}/script", json={"manual_text": "# शुरुआत\nरायगढ़ किला बहुत ऊँचा है। यहाँ शिवाजी रहते थे।\n\nआज लोग यहाँ घूमने आते हैं।"})
    assert r.status_code == 200 and len(r.json()["script"]["chapters"]) == 2
    g = _wait(authed, authed.post(f"/api/projects/{pid}/generate", json={}).json()["job_id"])
    assert g["status"] == "done", g
    notices = " ".join(g["result"]["notices"])
    assert "टेम्पलेट" in notices                     # metadata from template without a key
    st = authed.get(f"/api/projects/{pid}/create-state").json()
    assert st["meta"]["source"] == "template" and st["outputs"][0]["meta"]["aspect"] == "1:1"


def test_fallback_notice_when_first_llm_fails(authed, offline, monkeypatch):
    from app.providers.base import ProviderError

    def limited(*a, **k):
        raise ProviderError("rate_limited", "Groq: limit पूरी हो गई (429).", 0.01)

    monkeypatch.setattr(registry.get("groq"), "impl", limited)
    monkeypatch.setattr(registry.get("gemini"), "impl", scripted_llm())
    monkeypatch.setattr(registry, "MAX_RETRY_WAIT_S", 0.01)
    pid = _make(authed, 1, "16:9")
    hdr = {"X-Provider-Keys": encode_keys_header({"groq": {"apiKey": "a1b2c3d4"}, "gemini": {"apiKey": "e5f6g7h8"}})}
    j = _wait(authed, authed.post(f"/api/projects/{pid}/script", json={}, headers=hdr).json()["job_id"])
    assert j["status"] == "done"
    assert any("Gemini पर switch" in x["msg"] for x in j["log"]), [x["msg"] for x in j["log"]]
    # all LLMs failing: step stops, earlier work kept, clear error
    monkeypatch.setattr(registry.get("gemini"), "impl", limited)
    j = _wait(authed, authed.post(f"/api/projects/{pid}/script", json={"fresh": True}, headers=hdr).json()["job_id"])
    assert j["status"] == "failed" and "विफल" in j["error"]
    st = authed.get(f"/api/projects/{pid}/create-state").json()
    assert st["project"]["status"] == "script_failed" and st["script"] is not None   # previous script kept


SENTINEL = "SENTINEL-KEY-b17c0d9e4a2f"


def test_sentinel_key_through_workflow_b(authed, offline, data_dir, monkeypatch, caplog):
    def leaky_llm(system, user, keys, json_mode=False, model=None):
        logging.getLogger("app").info("llm called with %s", keys["apiKey"])
        return scripted_llm()(system, user, keys, json_mode)

    monkeypatch.setattr(registry.get("groq"), "impl", leaky_llm)
    monkeypatch.setattr(requests, "request", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError(SENTINEL)))
    caplog.set_level(logging.INFO)
    hdr = {"X-Provider-Keys": encode_keys_header({"groq": {"apiKey": SENTINEL}, "pexels": {"apiKey": SENTINEL}})}
    pid = _make(authed, 1, "16:9")
    for path, body in ((f"/api/projects/{pid}/research", None), (f"/api/projects/{pid}/script", {}),
                       (f"/api/projects/{pid}/generate", {})):
        r = authed.post(path, json=body, headers=hdr)
        assert r.status_code == 200, r.text
        j = _wait(authed, r.json()["job_id"])
        assert SENTINEL not in str(j)
    blob = b"".join(p.read_bytes() for p in data_dir.rglob("*") if p.is_file())
    assert SENTINEL.encode() not in blob
    assert SENTINEL not in caplog.text


@pytest.mark.skipif(not SLOW, reason="slow (≈3 min render each) — run with AIYT_SLOW=1 in the acceptance run")
def test_three_minute_runs_16x9_and_9x16(authed, offline):
    for aspect in ("16:9", "9:16"):
        pid, g, st, took = _run_full(authed, 3, aspect)
        res = _check_run(authed, pid, g, st, 3, aspect)
        (ARTIFACTS / "timings.txt").open("a", encoding="utf-8").write(
            f"3-min {aspect}: video {res['duration_s']:.1f}s, generate {took:.1f}s, scenes {res['scenes']}\n")
        assert took < 15 * 60          # PRD target: 3-minute video in ≤ 15 minutes
