"""Provider adapter interface (PRD §6.2). Keys are passed per call and never stored."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import requests

CAPABILITIES = ("llm", "tts", "stt", "image", "stock", "avatar")
TIMEOUT = 30


@dataclass(frozen=True)
class KeySpec:
    name: str
    label: str
    docs_url: str


class ProviderError(Exception):
    """kind: 'invalid_key' | 'rate_limited' | 'transient' | 'bad_output' | 'unavailable' | 'error'"""

    def __init__(self, kind: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


@dataclass
class Provider:
    id: str
    label: str
    capability: str
    tier: str  # "free" | "premium"
    requires_keys: list[KeySpec] = field(default_factory=list)
    limits_note: str = ""
    docs_url: str = ""
    languages: list[str] = field(default_factory=lambda: ["hi", "en"])
    enabled: bool = True  # premium placeholders are disabled ("coming later")
    note: str = ""
    priority: int = 100
    health_fn: Callable[[dict[str, str]], None] | None = None
    impl: Any = None  # capability-specific callable(s)
    key_source: str | None = None  # reuse another provider's saved key (e.g. Groq Whisper -> groq)

    def keys_for(self, all_keys: dict[str, dict[str, str]]) -> dict[str, str]:
        return all_keys.get(self.key_source or self.id, {})

    def has_keys(self, all_keys: dict[str, dict[str, str]]) -> bool:
        mine = self.keys_for(all_keys)
        return all(mine.get(k.name) for k in self.requires_keys)

    def health_check(self, keys: dict[str, str]) -> dict:
        if not self.enabled:
            return {"status": "unavailable", "message": "यह provider अभी उपलब्ध नहीं है (जल्द आ रहा है)।"}
        missing = [k.label for k in self.requires_keys if not keys.get(k.name)]
        if missing:
            return {"status": "not_set", "message": "Key नहीं डाली गई: " + ", ".join(missing)}
        if self.health_fn is None:
            return {"status": "valid", "message": "कोई key ज़रूरी नहीं।"}
        try:
            self.health_fn(keys)
            return {"status": "valid", "message": "Key सही है।"}
        except ProviderError as e:
            status = {"invalid_key": "invalid", "rate_limited": "rate_limited"}.get(e.kind, "error")
            return {"status": status, "message": str(e)}

    def meta(self) -> dict:
        return {
            "id": self.id, "label": self.label, "capability": self.capability, "tier": self.tier,
            "requires_keys": [vars(k) for k in self.requires_keys], "limits_note": self.limits_note,
            "docs_url": self.docs_url, "languages": self.languages, "enabled": self.enabled,
            "note": self.note, "priority": self.priority, "key_source": self.key_source,
        }


def check_response(resp: requests.Response, who: str) -> requests.Response:
    """Map an HTTP response to ProviderError kinds. Never includes request headers/keys."""
    if resp.status_code < 400:
        return resp
    retry_after = None
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            retry_after = float(ra)
        except ValueError:
            retry_after = None
    snippet = resp.text[:200].replace("\n", " ")
    if resp.status_code in (401, 403):
        raise ProviderError("invalid_key", f"{who}: key अमान्य है ({resp.status_code}).")
    if resp.status_code == 429:
        raise ProviderError("rate_limited", f"{who}: limit पूरी हो गई (429).", retry_after)
    if resp.status_code >= 500:
        raise ProviderError("transient", f"{who}: सर्वर त्रुटि {resp.status_code}: {snippet}", retry_after)
    raise ProviderError("error", f"{who}: त्रुटि {resp.status_code}: {snippet}")


def http(method: str, url: str, who: str, **kw) -> requests.Response:
    kw.setdefault("timeout", TIMEOUT)
    try:
        resp = requests.request(method, url, **kw)
    except requests.Timeout:
        raise ProviderError("transient", f"{who}: समय सीमा पार (timeout).")
    except requests.ConnectionError:
        raise ProviderError("transient", f"{who}: कनेक्शन नहीं हो सका।")
    return check_response(resp, who)
