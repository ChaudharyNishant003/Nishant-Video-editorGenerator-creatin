import time


def _wait(client, job_id, statuses, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job did not reach {statuses}: {job}")


def test_selftest_job_runs_with_progress(authed):
    job_id = authed.post("/api/jobs/selftest", json={"seconds": 2}).json()["job_id"]
    job = _wait(authed, job_id, ("done", "failed"))
    assert job["status"] == "done", job
    assert job["progress"] == 100
    assert any("Selftest पूरा" in e["msg"] for e in job["log"])


def test_cancel_kills_ffmpeg_within_seconds(authed):
    job_id = authed.post("/api/jobs/selftest", json={"seconds": 600}).json()["job_id"]
    job = _wait(authed, job_id, ("running",))
    time.sleep(1.0)  # let ffmpeg actually start encoding
    t0 = time.time()
    assert authed.post(f"/api/jobs/{job_id}/cancel").json() == {"cancelled": True}
    job = _wait(authed, job_id, ("cancelled", "failed", "done"), timeout=10)
    elapsed = time.time() - t0
    assert job["status"] == "cancelled", job
    # run_ffmpeg only returns after proc.wait(), so 'cancelled' implies ffmpeg has exited.
    assert elapsed < 5, f"cancel took {elapsed:.1f}s"


def test_sse_stream_ends_with_terminal_state(authed):
    job_id = authed.post("/api/jobs/selftest", json={"seconds": 1}).json()["job_id"]
    with authed.stream("GET", f"/api/jobs/{job_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [line for line in r.iter_lines() if line.startswith("data: ")]
    assert '"status": "done"' in events[-1] or '"status":"done"' in events[-1]
