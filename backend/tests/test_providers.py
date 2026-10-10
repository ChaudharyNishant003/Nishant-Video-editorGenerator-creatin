import os
import tempfile
from pathlib import Path

import pytest
import requests

from app.providers import registry
from app.providers.base import CAPABILITIES, Provider, ProviderError, check_response


class _R:
    def __init__(self, status, headers=None, text=""):
        self.status_code, self.headers, self.text = status, headers or {}, text


def test_registry_shape_and_contract():
    meta = registry.metadata()
    assert set(meta) == set(CAPABILITIES)
    for cap, items in meta.items():
        assert items, cap
        for p in items:
            assert p["tier"] in ("free", "premium")
            assert p["label"] and p["capability"] == cap
            for k in p["requires_keys"]:
                assert k["docs_url"].startswith("https://")
    # free first, premium after; premium placeholders disabled in MVP 1
    for cap, items in meta.items():
        tiers = [p["tier"] for p in items]
        assert tiers == sorted(tiers, key=lambda t: t != "free")
        assert all(not p["enabled"] for p in items if p["tier"] == "premium")
    assert registry.get("groq_whisper").key_source == "groq"


@pytest.mark.parametrize("status,kind", [(401, "invalid_key"), (403, "invalid_key"), (429, "rate_limited"),
                                         (503, "transient"), (400, "error")])
def test_http_status_mapping(status, kind):
    with pytest.raises(ProviderError) as e:
        check_response(_R(status, {"retry-after": "3"}), "X")
    assert e.value.kind == kind


def test_health_check_statuses(monkeypatch):
    p = registry.get("groq")
    assert p.health_check({})["status"] == "not_set"
    monkeypatch.setattr(requests, "request", lambda *a, **k: _R(200))
    assert p.health_check({"apiKey": "abcdefgh"})["status"] == "valid"
    monkeypatch.setattr(requests, "request", lambda *a, **k: _R(401))
    assert p.health_check({"apiKey": "abcdefgh"})["status"] == "invalid"
    monkeypatch.setattr(requests, "request", lambda *a, **k: _R(429))
    assert p.health_check({"apiKey": "abcdefgh"})["status"] == "rate_limited"
    assert registry.get("sarvam_bulbul").health_check({"apiKey": "x"})["status"] == "unavailable"
    assert registry.get("edge_tts").health_check({})["status"] == "valid"


def test_chain_never_auto_adds_premium():
    keys = {"groq": {"apiKey": "a" * 8}, "gemini": {"apiKey": "b" * 8}}
    ids = [p.id for p in registry.chain("llm", "groq", keys)]
    assert ids == ["groq", "gemini"]  # openrouter has no key -> skipped
    assert all(p.tier == "free" for p in registry.chain("tts", None, {}))


def test_fallback_switches_with_notice_and_retries(monkeypatch):
    keys = {"groq": {"apiKey": "a" * 8}, "gemini": {"apiKey": "b" * 8}}
    calls, notices, sleeps = [], [], []

    def call(p: Provider, k):
        calls.append(p.id)
        if p.id == "groq":
            raise ProviderError("rate_limited", "Groq: limit", retry_after=3)
        return "ok-from-" + p.id

    result, used = registry.run_with_fallback("llm", "groq", keys, call, notices.append, sleeps.append)
    assert result == "ok-from-gemini" and used.id == "gemini"
    assert calls == ["groq", "groq", "gemini"]  # one retry on rate limit, then switch
    assert sleeps == [3.0]
    assert any("Gemini" in n and "switch" in n for n in notices)


def test_fallback_all_fail_raises():
    with pytest.raises(ProviderError) as e:
        registry.run_with_fallback("llm", "groq", {"groq": {"apiKey": "a" * 8}},
                                   lambda p, k: (_ for _ in ()).throw(ProviderError("invalid_key", "bad")),
                                   sleep=lambda s: None)
    assert e.value.kind == "all_failed"


def test_unexpected_adapter_exception_becomes_provider_error():
    keys = {"groq": {"apiKey": "a" * 8}, "gemini": {"apiKey": "b" * 8}}
    result, used = registry.run_with_fallback(
        "llm", "groq", keys,
        lambda p, k: (_ for _ in ()).throw(KeyError("choices")) if p.id == "groq" else "ok",
        sleep=lambda s: None)
    assert result == "ok" and used.id == "gemini"


# --- real network, no key needed ------------------------------------------------
@pytest.mark.network
def test_edge_tts_hindi_word_timings_real():
    from app.providers.speech import edge_tts_synthesize
    out = Path(tempfile.mkdtemp()) / "t.mp3"
    res = edge_tts_synthesize("नमस्ते, यह एक परीक्षण है।", {}, out, voice="hi-IN-SwaraNeural")
    assert out.stat().st_size > 1000
    assert len(res["words"]) >= 3
    assert all(w["end"] > w["start"] >= 0 for w in res["words"])


# --- real provider keys (owner adds them on the Settings page later) -----------------
NEEDS_KEY = pytest.mark.skip(reason="not tested — needs key (owner will add on Settings page and ask for a re-run)")


@NEEDS_KEY
@pytest.mark.needs_key
def test_groq_chat_real():
    pass


@NEEDS_KEY
@pytest.mark.needs_key
def test_gemini_chat_real():
    pass


@NEEDS_KEY
@pytest.mark.needs_key
def test_groq_whisper_hindi_word_timestamps_real():
    pass


@NEEDS_KEY
@pytest.mark.needs_key
def test_pexels_pixabay_search_and_cache_real():
    pass
