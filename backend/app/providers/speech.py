"""TTS and STT adapters.

TTS: Edge-TTS (free, no key; unofficial Microsoft endpoint, LGPL-3.0) with word timings via
WordBoundary events (verified for hi-IN-SwaraNeural / MadhurNeural on 2026-10-10).
STT: Groq Whisper (shares the Groq key) with word timestamps; faster-whisper is an optional
local fallback that is only enabled if the package is installed.
"""

import asyncio
import importlib.util
from pathlib import Path

from .base import KeySpec, Provider, ProviderError, http
from .llm import GROQ_KEY

EDGE_VOICES = {
    "hi": ["hi-IN-SwaraNeural", "hi-IN-MadhurNeural"],
    "en": ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural"],
}


async def _edge_synth(text: str, voice: str, out_path: Path, rate: str | None) -> list[dict]:
    import edge_tts

    kwargs = {"boundary": "WordBoundary"}
    if rate:
        kwargs["rate"] = rate
    words: list[dict] = []
    with open(out_path, "wb") as f:
        async for ch in edge_tts.Communicate(text, voice, **kwargs).stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append({"text": ch["text"], "start": round(start, 3), "end": round(start + ch["duration"] / 1e7, 3)})
    return words


def edge_tts_synthesize(text: str, keys: dict, out_path: Path, voice: str = "hi-IN-SwaraNeural", rate: str | None = None) -> dict:
    """Returns {"path", "words": [{text,start,end}]} (seconds). Raises ProviderError on failure."""
    try:
        words = asyncio.run(_edge_synth(text, voice, Path(out_path), rate))
    except Exception as e:  # network / endpoint changes
        raise ProviderError("transient", f"Edge-TTS: आवाज़ नहीं बन सकी ({type(e).__name__}).")
    if not Path(out_path).exists() or Path(out_path).stat().st_size == 0:
        raise ProviderError("bad_output", "Edge-TTS: ख़ाली audio मिला।")
    return {"path": str(out_path), "words": words}


def groq_whisper_transcribe(audio_path: Path, keys: dict, language: str = "hi", model: str = "whisper-large-v3-turbo") -> dict:
    """Returns {"language", "text", "words": [{text,start,end}]}. File must be <= 25 MB on the free tier."""
    p = Path(audio_path)
    if p.stat().st_size > 25 * 1024 * 1024:
        raise ProviderError("error", "Groq Whisper: audio 25 MB से बड़ा है।")
    with open(p, "rb") as f:
        resp = http("POST", "https://api.groq.com/openai/v1/audio/transcriptions", "Groq Whisper",
                    headers={"Authorization": f"Bearer {keys['apiKey']}"},
                    files={"file": (p.name, f, "audio/mpeg")},
                    data={"model": model, "response_format": "verbose_json", "language": language,
                          "timestamp_granularities[]": "word"},
                    timeout=300)
    data = resp.json()
    words = [{"text": w.get("word", "").strip(), "start": float(w["start"]), "end": float(w["end"])}
             for w in data.get("words") or [] if "start" in w and "end" in w]
    return {"language": data.get("language", language), "text": data.get("text", ""), "words": words}


def faster_whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _faster_whisper_health(keys):
    if not faster_whisper_available():
        raise ProviderError("unavailable", "faster-whisper install नहीं है (वैकल्पिक, धीमा)।")


def _groq_health(keys):
    http("GET", "https://api.groq.com/openai/v1/models", "Groq", headers={"Authorization": f"Bearer {keys['apiKey']}"})


PROVIDERS = [
    Provider("edge_tts", "Edge-TTS (Microsoft voices)", "tts", "free", [], "बिना key; अनौपचारिक endpoint, कभी भी बंद हो सकता है।",
             "https://github.com/rany2/edge-tts", priority=10, impl=edge_tts_synthesize,
             note="Hindi: Swara, Madhur. Word timings available."),
    Provider("kokoro", "Kokoro (local, optional)", "tts", "free", [], "स्थानीय मॉडल; अभी install नहीं।",
             "https://github.com/hexgrad/kokoro", priority=20, enabled=False, note="वैकल्पिक fallback — अभी उपलब्ध नहीं।"),
    Provider("sarvam_bulbul", "Sarvam Bulbul", "tts", "premium",
             [KeySpec("apiKey", "Sarvam API key", "https://www.sarvam.ai/api-pricing")],
             "Price unverified.", "https://www.sarvam.ai/api-pricing", priority=90, enabled=False, note="जल्द आ रहा है (MVP 2)।"),
    Provider("elevenlabs", "ElevenLabs (voice cloning)", "tts", "premium",
             [KeySpec("apiKey", "ElevenLabs API key", "https://elevenlabs.io/app/settings/api-keys")],
             "Price unverified.", "https://elevenlabs.io/pricing", priority=91, enabled=False, note="जल्द आ रहा है (MVP 2)।"),
    Provider("groq_whisper", "Groq Whisper", "stt", "free", [GROQ_KEY],
             "Free: 20 RPM, 7.2K audio-s/hour, 28.8K/day, 25 MB file (docs, 2026-09).",
             "https://console.groq.com/docs/speech-to-text", priority=10, health_fn=_groq_health,
             impl=groq_whisper_transcribe, note="Groq वाली key ही इस्तेमाल होती है।", key_source="groq"),
    Provider("faster_whisper", "faster-whisper (local)", "stt", "free", [], "स्थानीय, इस लैपटॉप पर धीमा।",
             "https://github.com/SYSTRAN/faster-whisper", priority=20, enabled=faster_whisper_available(),
             health_fn=_faster_whisper_health, note="वैकल्पिक fallback।"),
]
