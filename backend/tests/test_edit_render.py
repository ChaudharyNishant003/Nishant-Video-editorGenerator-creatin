"""Workflow A acceptance (PRD §14): real ffmpeg renders on a synthetic 60 s sample, end to end via the API."""

import os
import time
from pathlib import Path

import numpy as np
import pytest

from app.edit import pipeline
from app.render.probe import probe
from media_fixtures import DUR, audio_onsets, bar_source_time, frame_gray, make_sample, save_png

ARTIFACTS = Path(os.environ.get("AIYT_TEST_ARTIFACTS", Path(__file__).resolve().parent / ".artifacts"))

# Conjunct-heavy Hindi words (PRD §11.2), placed inside the tone bursts.
HINDI = ["क्षत्रिय", "श्रीमान", "द्वारा", "कर्मचारियों", "ज्ञान", "राष्ट्र", "महत्वपूर्ण", "पूर्ण"]


def synthetic_words():
    words = []
    for k in range(15):
        base = 4 * k
        for j in range(3):
            words.append({"text": HINDI[(3 * k + j) % len(HINDI)], "start": base + 0.2 + 0.7 * j, "end": base + 0.8 + 0.7 * j})
    return words


def wait_job(client, job_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.3)
    raise AssertionError("job timeout")


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make_sample(tmp_path_factory.mktemp("media") / "sample.mp4")


def new_project(client, sample_path):
    pid = client.post("/api/projects", json={"kind": "edit", "title": "test"}).json()["id"]
    with open(sample_path, "rb") as f:
        r = client.post(f"/api/projects/{pid}/upload?kind=source&name=sample.mp4", content=f.read())
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job
    return pid


def render(client, pid, ops):
    r = client.put(f"/api/projects/{pid}/plan", json={"plan": {"ops": ops}, "prompt": "test"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/approve-and-render")
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", (job["error"], job["log"][-5:])
    return job["result"]


def output_path(pid, result):
    from app import storage

    return Path(storage.get_asset(result["output_asset_id"])["path"])


def test_cut_overlay_zoom_captions(authed, sample):
    """PRD §14 A-1/A-2: cut + overlay + zoom + captions; duration = time map; cut boundaries within 0.2 s."""
    pid = new_project(authed, sample)
    pipeline.save_transcript(pid, "test", "hi", synthetic_words())
    ops = [{"type": "cut", "start": 12, "end": 18},
           {"type": "text_overlay", "start": 30, "end": 33, "text": "महत्वपूर्ण: क्षत्रिय श्रीमान", "position": "center"},
           {"type": "zoom", "start": 40, "end": 45, "scale": 1.4},
           {"type": "captions", "style": "hindi_bold_word_highlight"}]
    res = render(authed, pid, ops)
    out = output_path(pid, res)
    assert abs(res["expected_s"] - (DUR - 6)) < 0.05
    assert abs(probe(out)["duration"] - res["expected_s"]) <= 0.1
    assert res["caption_words"] > 30
    # cut boundaries: just before the cut shows ~11.9 s, just after shows ~18.1 s
    for t_out, t_src in [(5.0, 5.0), (11.9, 11.9), (12.1, 18.1), (20.0, 26.0), (50.0, 56.0)]:
        got = bar_source_time(frame_gray(out, t_out))
        assert abs(got - t_src) <= 0.2, (t_out, t_src, got)
    # zoom 1.4 (centre) fully in at src 43 s → out 37 s: bar is wider and pushed away from the centre
    f = frame_gray(out, 37.0)
    bright = np.where(f[:40].mean(axis=0) > 128)[0]
    expected_left = 320 + (43 * 640 / 60 - 320) * 1.4
    assert bright.size >= 8 and abs(bright.min() - expected_left) <= 8, (bright.min() if bright.size else None, expected_left)
    ARTIFACTS.mkdir(exist_ok=True)
    save_png(ARTIFACTS / "a1_overlay_and_captions.png", out, 24.2)   # src 30.2 s: overlay + caption
    save_png(ARTIFACTS / "a1_zoom.png", out, 37.0)                  # src 43 s: zoomed (bar wider)
    save_png(ARTIFACTS / "a1_captions.png", out, 1.0)


def test_remove_silence_keeps_av_sync(authed, sample):
    """PRD §14 A-5: silence removal on a sample with pauses; audio stays in sync with video."""
    pid = new_project(authed, sample)
    res = render(authed, pid, [{"type": "remove_silence"}])
    out = output_path(pid, res)
    assert len(res["cuts"]) == 15
    assert 38 < res["expected_s"] < 44
    onsets = audio_onsets(out)
    assert len(onsets) >= 14
    for t in onsets[1:]:
        src = bar_source_time(frame_gray(out, t + 0.05))
        nearest = round(src / 4) * 4
        assert abs(src - (nearest + 0.05)) <= 0.15, (t, src)


def test_cancelled_render_leaves_nothing_behind(authed, sample):
    from app import storage

    pid = new_project(authed, sample)
    authed.put(f"/api/projects/{pid}/plan", json={"plan": {"ops": [{"type": "zoom", "start": 1, "end": 50}]}})
    job_id = authed.post(f"/api/projects/{pid}/approve-and-render").json()["job_id"]
    t0 = time.time()
    while authed.get(f"/api/jobs/{job_id}").json()["progress"] < 8 and time.time() - t0 < 60:
        time.sleep(0.1)
    assert authed.post(f"/api/jobs/{job_id}/cancel").json()["cancelled"] is True
    job = wait_job(authed, job_id, timeout=15)
    assert job["status"] == "cancelled"
    renders = storage.project_dir(pid) / "renders"
    assert not renders.exists() or not any(renders.iterdir())
    st = authed.get(f"/api/projects/{pid}/state").json()
    assert st["project"]["status"] == "planned" and st["outputs"] == []


def test_speed_music_broll_cleanup(authed, sample, tmp_path):
    pid = new_project(authed, sample)
    music = tmp_path / "music.wav"
    img = tmp_path / "broll.png"
    import subprocess

    from app.render.ffmpeg import ffmpeg_exe
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=8", str(music)], check=True)
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
                    "-frames:v", "1", str(img)], check=True)
    m = authed.post(f"/api/projects/{pid}/upload?kind=music&name=music.wav", content=music.read_bytes()).json()["asset"]
    b = authed.post(f"/api/projects/{pid}/upload?kind=broll&name=broll.png", content=img.read_bytes()).json()["asset"]
    res = render(authed, pid, [
        {"type": "speed", "start": 10, "end": 20, "factor": 2.0},
        {"type": "music", "track": f"upload:{m['id']}", "volume": 0.2, "duck": True},
        {"type": "broll", "start": 30, "end": 34, "source": f"upload:{b['id']}", "mode": "overlay"},
        {"type": "broll", "start": 50, "end": 52, "source": f"upload:{b['id']}", "mode": "replace"},
        {"type": "audio_cleanup", "denoise": True, "loudnorm": True},
    ])
    out = output_path(pid, res)
    assert abs(res["expected_s"] - 55.0) < 0.05
    assert abs(probe(out)["duration"] - 55.0) <= 0.1
    # inside the speed-up: output 15 s ↔ source 20 s (10 + 5*2)
    assert abs(bar_source_time(frame_gray(out, 14.9)) - 19.8) <= 0.25
    # replace-mode b-roll: full frame is red-ish (gray ≈ 81) at source 51 s → output 46 s
    f = frame_gray(out, 46.0)
    assert 60 < f.mean() < 110
    ARTIFACTS.mkdir(exist_ok=True)
    save_png(ARTIFACTS / "a3_broll_overlay.png", out, 27.0)
