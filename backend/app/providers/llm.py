"""LLM adapters: Groq, Gemini, OpenRouter (free tiers). Keys go in headers, never in URLs."""

from .base import KeySpec, Provider, ProviderError, http

GROQ_KEY = KeySpec("apiKey", "Groq API key", "https://console.groq.com/keys")
GEMINI_KEY = KeySpec("apiKey", "Gemini API key", "https://aistudio.google.com/app/apikey")
OPENROUTER_KEY = KeySpec("apiKey", "OpenRouter API key", "https://openrouter.ai/keys")

DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.5-flash",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}


def _openai_chat(url: str, who: str, key: str, model: str, system: str, user: str, json_mode: bool, extra_headers=None) -> str:
    body = {"model": model, "temperature": 0.4,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **(extra_headers or {})}
    data = http("POST", url, who, json=body, headers=headers, timeout=120).json()
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content")
    if not text:
        raise ProviderError("bad_output", f"{who}: खाली जवाब मिला।")
    return text


def groq_chat(system: str, user: str, keys: dict, json_mode: bool = False, model: str | None = None) -> str:
    return _openai_chat("https://api.groq.com/openai/v1/chat/completions", "Groq", keys["apiKey"],
                        model or DEFAULT_MODELS["groq"], system, user, json_mode)


def openrouter_chat(system: str, user: str, keys: dict, json_mode: bool = False, model: str | None = None) -> str:
    return _openai_chat("https://openrouter.ai/api/v1/chat/completions", "OpenRouter", keys["apiKey"],
                        model or DEFAULT_MODELS["openrouter"], system, user, json_mode,
                        {"X-Title": "AI YT Studio"})


def gemini_chat(system: str, user: str, keys: dict, json_mode: bool = False, model: str | None = None) -> str:
    model = model or DEFAULT_MODELS["gemini"]
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.4, **({"responseMimeType": "application/json"} if json_mode else {})}}
    data = http("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", "Gemini",
                json=body, headers={"x-goog-api-key": keys["apiKey"]}, timeout=120).json()
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise ProviderError("bad_output", "Gemini: खाली जवाब मिला।")
    return text


def _groq_health(keys):
    http("GET", "https://api.groq.com/openai/v1/models", "Groq", headers={"Authorization": f"Bearer {keys['apiKey']}"})


def _gemini_health(keys):
    http("GET", "https://generativelanguage.googleapis.com/v1beta/models", "Gemini", headers={"x-goog-api-key": keys["apiKey"]})


def _openrouter_health(keys):
    http("GET", "https://openrouter.ai/api/v1/key", "OpenRouter", headers={"Authorization": f"Bearer {keys['apiKey']}"})


PROVIDERS = [
    Provider("groq", "Groq", "llm", "free", [GROQ_KEY], "Free tier; limits per model — see console (as of 2026-10).",
             "https://console.groq.com/docs/rate-limits", priority=10, health_fn=_groq_health, impl=groq_chat),
    Provider("gemini", "Google Gemini", "llm", "free", [GEMINI_KEY], "Free tier RPM/RPD not verified (2026-10).",
             "https://ai.google.dev/gemini-api/docs/rate-limits", priority=20, health_fn=_gemini_health, impl=gemini_chat),
    Provider("openrouter", "OpenRouter (free models)", "llm", "free", [OPENROUTER_KEY],
             "':free' models; failed requests may still count (2026-10).",
             "https://openrouter.ai/docs/api_reference/limits", priority=30, health_fn=_openrouter_health, impl=openrouter_chat),
]
