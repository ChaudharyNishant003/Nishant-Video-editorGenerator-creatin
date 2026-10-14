"""Workflow B units: models/validators, research, LLM repair/fallback, mouth/blink tracks, transliteration,
pack metadata, Wikimedia + stock cache, visual fallbacks."""

import json

import numpy as np
import pytest
import requests

from app.create import avatar as av
from app.create import llmjson, pack, research, script as scriptgen, visuals
from app.create.models import (ScriptError, manual_script, resolve_layouts, validate_chapter, validate_facts,
                               validate_outline, validate_settings)
from app.providers import media, registry
from app.providers.base import ProviderError
from app.render.translit import to_roman
from create_fixtures import scripted_llm


# --- models ---------------------------------------------------------------------------------------
def test_settings_are_clamped_to_known_values():
    s = validate_settings({"topic": "  रायगढ़   किला ", "minutes": 9, "aspect": "4:3", "character": "nobody",
                           "outfit": "pink", "voice": "x", "layout": "weird", "caption_script": "roman", "music_volume": 7})
    assert s.topic == "रायगढ़ किला" and s.minutes == 5 and s.aspect == "16:9"
    assert s.character in av.characters() and s.outfit == av.characters()[s.character]["outfits"][0]["id"]
    assert s.voice == "hi-IN-SwaraNeural" and s.layout == "auto" and s.caption_script == "roman" and s.music_volume == 1.0
    assert validate_settings("garbage").topic == ""


def test_facts_citing_unfetched_sources_become_uncertain():
    facts = validate_facts({"facts": [
        {"text": "A", "source_url": "https://hi.wikipedia.org/wiki/Raigad"},
        {"text": "B", "source_url": "https://evil.example/fake"},
        {"text": "C", "source_url": "notes"}, {"text": "D"}, {"text": "   "}, "E as plain string", 42]},
        allowed_sources={"https://hi.wikipedia.org/wiki/Raigad", "notes"})
    assert [f.text for f in facts] == ["A", "B", "C", "D", "E as plain string"]
    assert [f.uncertain for f in facts] == [False, True, False, True, True]
    assert [f.id for f in facts] == ["f1", "f2", "f3", "f4", "f5"]
    with pytest.raises(ScriptError):
        validate_facts({"nope": 1})


def test_chapter_validation_repairs_llm_output():
    ch = validate_chapter({"title": "शुरुआत", "scenes": [
        {"text": "पहला वाक्य।", "layout": "spaceship", "visual": {"kind": "hologram", "query": "fort"}},
        {"text": "", "visual": "x"},
        "दूसरा वाक्य सिर्फ़ टेक्स्ट।",
        {"text": "तीसरा", "visual": {"kind": "stock_video", "query": ""}, "fact_refs": ["f1", "f99"], "est_seconds": 900}]},
        2, topic="Raigad", fact_ids={"f1"})
    assert [s.id for s in ch.scenes] == ["c2s1", "c2s2", "c2s3"]
    assert ch.scenes[0].layout == "auto" and ch.scenes[0].visual.kind == "ai_image"
    assert ch.scenes[1].visual.query == "Raigad"           # falls back to topic
    assert ch.scenes[2].fact_refs == ["f1"] and ch.scenes[2].est_seconds == 120.0
    with pytest.raises(ScriptError):
        validate_chapter({"scenes": [{"text": ""}]}, 1)
    narr = validate_chapter({"narration": "एक। दो? तीन!"}, 1)
    assert len(narr.scenes) == 3


def test_outline_validation():
    o = validate_outline({"title": "T", "chapters": ["एक", {"title": "दो", "summary": "s"}, {"x": 1}]}, 2)
    assert [c.title for c in o.chapters] == ["एक", "दो"]
    with pytest.raises(ScriptError):
        validate_outline({"chapters": []}, 2)


def test_manual_script_splits_paragraphs_and_sentences():
    text = "# परिचय\nयह पहला वाक्य है। यह दूसरा वाक्य है।\n\nदूसरा हिस्सा यहाँ है। " + "शब्द " * 40 + "अंत।"
    sc = manual_script(text, "रायगढ़")
    assert sc.manual and len(sc.chapters) == 2
    assert sc.chapters[0].title == "परिचय" and sc.chapters[1].title == "भाग 2"
    assert len(sc.chapters[0].scenes) == 1           # two short sentences fit in one scene
    assert len(sc.chapters[1].scenes) >= 2           # long text is split
    assert all(s.visual.kind == "ai_image" and "रायगढ़" in s.visual.query for c in sc.chapters for s in c.scenes)
    with pytest.raises(ScriptError):
        manual_script("   \n\n  ", "x")


def test_resolve_layouts_rotation_fixed_and_no_visual():
    sc = manual_script("एक। दो। तीन। चार। पाँच।", "t", max_words=1)
    sc.chapters[0].scenes[2].visual.kind = "none"
    auto = resolve_layouts(sc, "auto")
    assert len(set(auto.values())) >= 2 and auto["c1s3"] == "avatar_only"
    fixed = resolve_layouts(sc, "broll_fullscreen_avatar_corner")
    assert fixed["c1s1"] == "broll_fullscreen_avatar_corner" and fixed["c1s3"] == "avatar_only"


# --- research (mocked Wikipedia) --------------------------------------------------------------------
class _Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.headers, self.text = status, data, {}, json.dumps(data)

    def json(self):
        return self._data


def test_research_sources_and_facts(monkeypatch):
    calls = []

    def fake_request(method, url, **kw):
        calls.append((url, kw.get("params", {}).get("action"), kw.get("headers", {}).get("User-Agent")))
        p = kw.get("params", {})
        if p.get("list") == "search":
            return _Resp({"query": {"search": [{"title": "रायगढ़ किला" if "hi." in url else "Raigad Fort"}]}})
        return _Resp({"query": {"pages": [{"extract": "रायगढ़ किला। " * 60}]}})

    monkeypatch.setattr(requests, "request", fake_request)
    notices = []
    sources = research.gather_sources("रायगढ़", notices.append)
    assert [s["lang"] for s in sources] == ["hi", "en"]
    assert sources[0]["url"] == "https://hi.wikipedia.org/wiki/रायगढ़_किला"
    assert all(ua and "AIYTStudio" in ua for _, _, ua in calls)          # Wikimedia UA policy

    monkeypatch.setattr(registry.get("groq"), "impl", scripted_llm())
    s = validate_settings({"topic": "रायगढ़"})
    sources[0]["url"] = "https://hi.wikipedia.org/wiki/x"
    facts, prov = research.make_facts(s, sources, {"groq": {"apiKey": "k"}}, None, notices.append)
    assert prov == "Groq" and len(facts) == 3
    assert [f.uncertain for f in facts] == [False, False, True]          # made-up URL → uncertain


def test_research_survives_wikipedia_errors(monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **k: _Resp({}, 503))
    notices = []
    assert research.gather_sources("x", notices.append) == []
    assert len(notices) == 2 and all("Wikipedia" in n for n in notices)


# --- LLM repair / fallback ---------------------------------------------------------------------------
def test_script_llm_repair_then_fallback_with_notice(monkeypatch):
    replies = {"groq": ["not json", "still not json"], "gemini": [scripted_llm()("Make an outline with exactly 2 chapters.", "", {})]}

    def make(name):
        def impl(system, user, keys, json_mode=False, model=None):
            return replies[name].pop(0)
        return impl

    monkeypatch.setattr(registry.get("groq"), "impl", make("groq"))
    monkeypatch.setattr(registry.get("gemini"), "impl", make("gemini"))
    notes = []
    s = validate_settings({"topic": "t", "minutes": 2})
    outline, prov = scriptgen.make_outline(s, [], {"groq": {"apiKey": "a"}, "gemini": {"apiKey": "b"}}, None, notes.append)
    assert prov == "Google Gemini" and len(outline.chapters) == 2
    assert any("सुधार" in n for n in notes) and any("switch" in n for n in notes)


def test_script_all_llms_fail_cleanly(monkeypatch):
    monkeypatch.setattr(registry.get("groq"), "impl", lambda *a, **k: "garbage")
    with pytest.raises(ProviderError) as e:
        scriptgen.make_outline(validate_settings({"topic": "t"}), [], {"groq": {"apiKey": "a"}}, None, lambda m: None)
    assert e.value.kind == "all_failed"
    with pytest.raises(ProviderError):
        scriptgen.make_outline(validate_settings({"topic": "t"}), [], {}, None, lambda m: None)


def test_premium_is_never_used_automatically():
    assert all(p.tier == "free" for p in registry.chain("llm", None, {"groq": {"apiKey": "a"}}))
    assert all(p.tier == "free" for p in registry.chain("tts", None, {}))
    assert llmjson.has_llm({}) is False and llmjson.has_llm({"gemini": {"apiKey": "x"}}) is True


def test_chapter_prompt_word_budget_and_language(monkeypatch):
    seen = []
    monkeypatch.setattr(registry.get("groq"), "impl", scripted_llm(log=seen))
    s = validate_settings({"topic": "t", "minutes": 3, "language": "hinglish"})
    outline, _ = scriptgen.make_outline(s, [], {"groq": {"apiKey": "a"}}, None, lambda m: None)
    assert len(outline.chapters) == scriptgen.chapter_count(3) == 3
    assert "Devanagari" in scriptgen.language_rule(s) and "टेक्नोलॉजी" in scriptgen.language_rule(s)
    ch, _ = scriptgen.make_chapter(s, outline, 0, [], {"groq": {"apiKey": "a"}}, None, lambda m: None)
    assert ch.scenes and all(sc.id.startswith("c1s") for sc in ch.scenes)


# --- avatar tracks -----------------------------------------------------------------------------------
def test_mouth_levels_follow_loudness_with_hysteresis():
    env = np.array([0.0] * 10 + [0.5] * 10 + [0.0] * 10 + [0.2] * 10, np.float32)
    lv = av.mouth_levels(env, 40)
    assert max(lv[:8]) == 0 and min(lv[12:18]) >= 2 and max(lv[23:30]) == 0 and 1 <= lv[35] <= 2
    assert av.mouth_levels(np.zeros(0, np.float32), 5) == [0] * 5


def test_blinks_every_3_to_6_seconds_and_sway_small():
    fps = 24
    b = av.blink_track(fps * 60, fps, seed=3)
    starts = [i for i in range(1, len(b)) if b[i] and not b[i - 1]]
    gaps = np.diff(starts) / fps
    assert len(starts) >= 9 and gaps.min() >= 2.9 and gaps.max() <= 6.1
    sway = av.sway_track(fps * 10, fps)
    assert set(sway) <= {0, 1, 2} and len(set(sway)) > 1


def test_catalog_has_characters_backgrounds_and_safe_files():
    cat = av.catalog()
    assert {c["id"] for c in cat["characters"]} == {"aarav", "meera", "dadaji"}
    assert len(cat["backgrounds"]) == 3 and all(len(c["outfits"]) == 3 for c in cat["characters"])
    assert av.asset_file(cat["characters"][0]["preview"]) is not None
    assert av.asset_file("../../config.py") is None and av.asset_file("characters/aarav/config.json") is None


# --- transliteration ---------------------------------------------------------------------------------
@pytest.mark.parametrize("dev,rom", [("राजा", "raja"), ("रखना", "rakhna"), ("समझना", "samajhna"), ("कमल", "kamal"),
                                     ("परंपरा", "parampara"), ("क्षत्रिय", "kshatriya"), ("ज़िंदगी", "zindagi"),
                                     ("में", "mein"), ("नमस्ते", "namaste"), ("भारत", "bharat")])
def test_roman_transliteration(dev, rom):
    assert to_roman(dev) == rom


def test_roman_keeps_punctuation_and_latin():
    assert to_roman("यह AI है। १२३") == "yeh AI hai. 123"


# --- pack ----------------------------------------------------------------------------------------
def test_template_meta_and_description_timestamps():
    m = pack.template_meta("रायगढ़ किला", "रायगढ़", ["शुरुआत", "इतिहास"])
    assert len(m["titles"]) == 3 and set(m["platforms"]) == set(pack.PLATFORMS)
    d = pack.youtube_description("परिचय।", [(0, "शुरुआत"), (65.4, "इतिहास"), (3725, "अंत")], ["Wiki — https://x"], ["Photo by A on Pexels"])
    assert "0:00 शुरुआत" in d and "1:05 इतिहास" in d and "1:02:05 अंत" in d
    assert "Photo by A on Pexels" in d and pack.DISCLOSURE_LINE in d


def test_validate_meta_cleans_llm_output():
    m = pack.validate_meta({"titles": ["  एक  ", "", "दो", "तीन", "चार"], "tags": ["#a", "a", " b ", 5],
                            "platforms": {"instagram": {"hashtags": ["x y", "#z"]}, "linkedin": "bad"}})
    assert m["titles"] == ["एक", "दो", "तीन"] and m["tags"] == ["a", "b", "5"]
    assert m["platforms"]["instagram"]["hashtags"] == ["#xy", "#z"] and m["platforms"]["linkedin"]["title"] == "एक"
    with pytest.raises(ValueError):
        pack.validate_meta({"titles": []})


# --- wikimedia + stock cache + visual fallbacks ---------------------------------------------------------
def test_wikimedia_search_parses_and_caches(monkeypatch):
    calls = []

    def fake_request(method, url, **kw):
        calls.append(url)
        return _Resp({"query": {"pages": [
            {"index": 2, "title": "File:Small.jpg", "imageinfo": [{"mime": "image/jpeg", "width": 100, "url": "u0"}]},
            {"index": 1, "title": "File:Raigad.jpg", "imageinfo": [{"mime": "image/jpeg", "width": 2000, "url": "u1",
                                                                  "thumburl": "t1", "extmetadata": {"Artist": {"value": "<a>Ravi</a>"},
                                                                                                    "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}]}})

    monkeypatch.setattr(requests, "request", fake_request)
    q = "raigad-unique-query-1"
    items = media.wikimedia_search(q, {})
    assert len(items) == 1 and items[0]["url"] == "t1"
    assert "Ravi" in items[0]["attribution"] and "CC BY-SA 4.0" in items[0]["attribution"]
    media.wikimedia_search(q, {})
    assert len(calls) == 1                      # second call served from the 24 h cache


def test_stock_search_cached_for_24h(monkeypatch):
    calls = []

    def fake_request(method, url, **kw):
        calls.append(url)
        return _Resp({"photos": [{"src": {"large2x": "https://p/1.jpg"}, "photographer": "Asha", "url": "page"}]})

    monkeypatch.setattr(requests, "request", fake_request)
    a = media.pexels_search("cache-test-query", {"apiKey": "k"})
    b = media.pexels_search("cache-test-query", {"apiKey": "k"})
    assert a == b and len(calls) == 1 and a[0]["attribution"] == "Photo by Asha on Pexels"


def test_visual_fallback_chain(monkeypatch, tmp_path):
    from create_fixtures import fake_image

    used = []
    monkeypatch.setattr(registry.get("wikimedia"), "impl", lambda q, k, **kw: used.append(("wiki", q)) or [])
    monkeypatch.setattr(visuals, "pollinations_generate", fake_image())
    notes = []
    # stock requested without stock keys → Wikimedia (nothing) → Pollinations
    v = visuals.fetch_visual("stock_video", "fort", [], "16:9", tmp_path, {}, notes.append)
    assert v["provider"] == "pollinations" and ("wiki", "fort") in used
    # everything fails → None + notice (scene becomes avatar_only)
    monkeypatch.setattr(visuals, "pollinations_generate", lambda *a, **k: (_ for _ in ()).throw(ProviderError("transient", "down")))
    assert visuals.fetch_visual("ai_image", "fort2", [], "9:16", tmp_path, {}, notes.append) is None
    assert any("सिर्फ़ अवतार" in n for n in notes)
    assert visuals.fetch_visual("none", "x", [], "16:9", tmp_path, {}, notes.append) is None
