"""PRD §6.5 / §14: a unique fake key must never appear in the DB, the data dir, or logs."""

import logging
import time
from pathlib import Path

import requests

from app.providers import base as pbase
from app.security.keys import encode_keys_header
from app.security.redact import redact

SENTINEL = "SENTINEL-KEY-7f3a9c2e1b5d4f60"


class _FakeResp:
    def __init__(self, status=200, text="{}", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def json(self):
        return {}


def _all_bytes_under(path: Path) -> bytes:
    out = b""
    for p in path.rglob("*"):
        if p.is_file():
            out += p.read_bytes()
    return out


def test_sentinel_key_never_persisted_or_logged(authed, data_dir, monkeypatch, caplog):
    seen_headers = []

    def fake_request(method, url, **kw):
        seen_headers.append(kw.get("headers", {}))
        # Simulate a provider echoing the key back in an error body.
        return _FakeResp(401, text=f"invalid api key {SENTINEL}")

    monkeypatch.setattr(requests, "request", fake_request)
    hdr = {"X-Provider-Keys": encode_keys_header({"groq": {"apiKey": SENTINEL}, "pexels": {"apiKey": SENTINEL}})}
    caplog.set_level(logging.INFO)

    # 1) key test endpoint (adapter receives the key, upstream "rejects" it)
    r = authed.post("/api/providers/groq/test", headers=hdr)
    assert r.status_code == 200 and r.json()["status"] == "invalid"
    assert SENTINEL not in r.text
    assert any(SENTINEL in str(h) for h in seen_headers), "adapter should have received the key in a header"

    # 2) a job that holds the key in memory and logs/raises text containing it
    job_id = authed.post("/api/jobs/selftest", json={"seconds": 1}, headers=hdr).json()["job_id"]
    from app.jobs import runner

    def leaky(ctx):
        ctx.log(f"debug {ctx.keys['groq']['apiKey']}")
        logging.getLogger("app").info("upstream said: key=%s", ctx.keys["groq"]["apiKey"])
        raise RuntimeError(f"provider failed for {ctx.keys['groq']['apiKey']}")

    leak_id = runner.submit("leaktest", leaky, keys={"groq": {"apiKey": SENTINEL}})
    for jid in (job_id, leak_id):
        for _ in range(100):
            if authed.get(f"/api/jobs/{jid}").json()["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.1)
    leak = authed.get(f"/api/jobs/{leak_id}").json()
    assert leak["status"] == "failed" and "[REDACTED]" in leak["error"]

    # 3) preferences refuse secret-looking keys
    assert authed.put("/api/preferences", json={"values": {"groq_api_key": SENTINEL}}).status_code == 400

    # 4) grep DB + data dir + captured logs
    blob = _all_bytes_under(data_dir)
    assert SENTINEL.encode() not in blob, "sentinel found in data dir / SQLite"
    assert SENTINEL not in caplog.text, "sentinel found in logs"


def test_redact_patterns():
    assert "[REDACTED]" in redact("Authorization: Bearer sk-abcdefghijklmnop")
    assert "gsk_abcdefghijklmnop" not in redact("token gsk_abcdefghijklmnop")
    assert "AIzaSyA1234567890abcdefghij" not in redact("x AIzaSyA1234567890abcdefghij y")
    assert redact("नमस्ते duniya") == "नमस्ते duniya"
