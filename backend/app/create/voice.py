"""Narration per scene (PRD §5.3 step 4). Scene durations come from the REAL audio, never from LLM guesses.
Audio + word timings are cached by hash(text, voice, rate), so resuming or re-rendering never re-calls TTS
for unchanged scenes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from ..providers import registry
from ..render.probe import probe
from .models import RATES

TAIL_PAD_S = 0.35  # breathing room after each scene's narration


def voice_key(text: str, voice: str, rate: str) -> str:
    return hashlib.sha256(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]


def synth_scene(text: str, voice: str, rate: str, dest: Path, all_keys: dict, preferred: str | None,
                notify: Callable[[str], None], force: bool = False, variant: int = 0) -> dict:
    """Returns {"key", "path", "duration" (measured audio + pad), "audio_s", "words": [{text,start,end}]}."""
    key = voice_key(text, voice, rate) + (f"v{variant}" if variant else "")
    audio, meta = dest / f"voice_{key}.mp3", dest / f"voice_{key}.json"
    if not force and audio.is_file() and meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    rate_arg = RATES.get(rate)

    def call(p, keys):
        return p.impl(text, keys, audio, voice=voice, rate=rate_arg)

    res, prov = registry.run_with_fallback("tts", preferred, all_keys, call, notify=notify)
    info = probe(audio)
    if not info["duration"] or info["duration"] <= 0.1:
        raise RuntimeError("आवाज़ की फ़ाइल ख़ाली है।")
    out = {"key": key, "path": str(audio), "audio_s": round(info["duration"], 3),
           "duration": round(info["duration"] + TAIL_PAD_S, 3), "words": res.get("words") or [], "provider": prov.id}
    meta.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
