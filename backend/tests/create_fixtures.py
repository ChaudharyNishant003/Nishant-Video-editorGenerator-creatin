"""Offline fakes for Workflow B tests: scripted LLM replies, tone-based TTS with word timings, synthetic images.

The fake TTS produces a 440 Hz tone that is ON while a word is "spoken" and silent between words/sentences,
so mouth movement can be checked against loudness, and durations are fully deterministic.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.render.ffmpeg import ffmpeg_exe

WORD_S, GAP_S, SENT_GAP_S = 0.42, 0.13, 0.45


def fake_tts_words(text: str) -> tuple[list[dict], float]:
    words, t = [], 0.1
    for w in text.split():
        words.append({"text": w, "start": round(t, 3), "end": round(t + WORD_S, 3)})
        t += WORD_S + (SENT_GAP_S if w.endswith(("।", "?", "!")) else GAP_S)
    return words, round(t, 3)


def fake_tts(calls: list | None = None):
    def impl(text, keys, out_path, voice="hi-IN-SwaraNeural", rate=None):
        if calls is not None:
            calls.append(text)
        words, dur = fake_tts_words(text)
        on = "+".join(f"between(t,{w['start']},{w['end']})" for w in words) or "0"
        subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"aevalsrc='0.5*sin(2*PI*440*t)*gt({on},0)':s=24000:d={dur}", "-c:a", "libmp3lame", "-b:a", "64k",
                        str(out_path)], check=True)
        return {"path": str(out_path), "words": words}
    return impl


def fake_image(calls: list | None = None):
    def impl(prompt, keys, width=1280, height=720, seed=None):
        if calls is not None:
            calls.append(prompt)
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                              f"testsrc2=size={width}x{height}", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                             capture_output=True, check=True).stdout
        return {"bytes": out, "mime": "image/jpeg", "source_url": "test", "attribution": "Image: Pollinations.ai (AI-generated)"}
    return impl


SENTENCES = [
    "रायगढ़ किला महाराष्ट्र के पहाड़ों में बना एक बहुत पुराना और ऊँचा किला है।",
    "शिवाजी महाराज ने इसे अपनी राजधानी बनाया और यहीं उनका राज्याभिषेक हुआ।",
    "किले तक पहुँचने के लिए आज रोपवे भी है और सीढ़ियाँ भी।",
    "यहाँ से चारों तरफ़ का नज़ारा बहुत सुंदर दिखता है।",
    "इतिहास पढ़ने वाले छात्रों के लिए यह जगह किसी किताब से कम नहीं।",
    "हर साल हज़ारों लोग यहाँ घूमने और सीखने आते हैं।",
]
KINDS = [("ai_image", "Raigad fort on a hill"), ("wiki_image", "Raigad Fort"), ("none", ""),
         ("stock_video", "mountain fort aerial"), ("ai_image", "students reading history"), ("stock_image", "tourists")]
LAYS = ["avatar_center_side_inserts", "broll_fullscreen_avatar_corner", "avatar_only", "auto"]


def chapter_json(no: int, n_scenes: int) -> str:
    scenes = []
    for i in range(n_scenes):
        k, q = KINDS[(no + i) % len(KINDS)]
        scenes.append({"text": SENTENCES[(no * 3 + i) % len(SENTENCES)], "layout": LAYS[(no + i) % len(LAYS)],
                       "visual": {"kind": k, "query": q}, "fact_refs": ["f1"]})
    return json.dumps({"title": f"अध्याय {no}", "scenes": scenes}, ensure_ascii=False)


def scripted_llm(minutes: int = 1, scenes_per_chapter: int | None = None, log: list | None = None):
    """A deterministic LLM that answers every Workflow B prompt type with valid JSON."""
    def impl(system, user, keys, json_mode=False, model=None):
        if log is not None:
            log.append(system[:40])
        if "fact-checker" in system:
            return json.dumps({"facts": [{"text": "रायगढ़ किला महाराष्ट्र में है।", "source_url": "notes"},
                                         {"text": "यहाँ राज्याभिषेक हुआ।", "source_url": "https://hi.wikipedia.org/wiki/x"},
                                         {"text": "किला 1656 में जीता गया।", "source_url": "https://made.up/source"}]},
                              ensure_ascii=False)
        if "make an outline" in system.lower():
            n = int(system.split("exactly ")[1].split(" ")[0])
            return json.dumps({"title": "रायगढ़ किले की कहानी",
                               "chapters": [{"title": f"हिस्सा {i + 1}", "summary": "…"} for i in range(n)]}, ensure_ascii=False)
        if "narration for chapter" in system:
            no = int(system.split("chapter ")[1].split(" ")[0])
            words = int(system.split("about ")[1].split(" ")[0])
            per = scenes_per_chapter or max(2, round(words / 15))
            return chapter_json(no, per)
        if "publishing metadata" in system:
            return json.dumps({"titles": ["रायगढ़: शिवाजी की राजधानी", "रायगढ़ किला", "किले की कहानी"],
                               "description": "रायगढ़ किले के बारे में एक छोटा वीडियो।", "tags": ["रायगढ़", "Raigad", "#history"],
                               "platforms": {"instagram": {"title": "रायगढ़", "text": "देखिए!", "hashtags": ["raigad", "#fort"]}}},
                              ensure_ascii=False)
        if "Transliterate" in system:
            return json.dumps({"map": {}})
        if "Rewrite ONE scene" in system:
            return json.dumps({"text": "यह नया और बेहतर वाक्य है।"}, ensure_ascii=False)
        return "{}"
    return impl


def silent_png(path: Path, w=640, h=360) -> Path:
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=0x3366aa:s={w}x{h}", "-frames:v", "1", str(path)], check=True)
    return path
