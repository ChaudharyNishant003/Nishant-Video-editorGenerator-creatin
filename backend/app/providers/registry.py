"""Provider registry + automatic free-only fallback (PRD §6.1, §6.6)."""

from __future__ import annotations

import time
from typing import Any, Callable

from . import llm, media, speech
from .base import CAPABILITIES, Provider, ProviderError

ALL: list[Provider] = [*llm.PROVIDERS, *speech.PROVIDERS, *media.PROVIDERS]
_BY_ID = {p.id: p for p in ALL}
assert len(_BY_ID) == len(ALL), "duplicate provider id"

MAX_ATTEMPTS_PER_PROVIDER = 2  # cap retries (OpenRouter counts failed requests)
MAX_RETRY_WAIT_S = 10.0


def get(provider_id: str) -> Provider:
    try:
        return _BY_ID[provider_id]
    except KeyError:
        raise ProviderError("error", f"अज्ञात provider: {provider_id}")


def by_capability(capability: str) -> list[Provider]:
    if capability not in CAPABILITIES:
        raise ProviderError("error", f"अज्ञात capability: {capability}")
    tier_rank = {"free": 0, "premium": 1}
    return sorted((p for p in ALL if p.capability == capability), key=lambda p: (tier_rank[p.tier], p.priority))


def metadata() -> dict:
    return {cap: [p.meta() for p in by_capability(cap)] for cap in CAPABILITIES}


def chain(capability: str, preferred_id: str | None, all_keys: dict) -> list[Provider]:
    """Preferred provider first (premium only if explicitly preferred), then other usable FREE providers."""
    out: list[Provider] = []
    if preferred_id:
        p = get(preferred_id)
        if p.capability != capability:
            raise ProviderError("error", f"{p.label} '{capability}' के लिए नहीं है।")
        if p.enabled:
            out.append(p)
    for p in by_capability(capability):
        if p in out or p.tier != "free" or not p.enabled or p.impl is None:
            continue
        if p.has_keys(all_keys):
            out.append(p)
    return out


def run_with_fallback(
    capability: str,
    preferred_id: str | None,
    all_keys: dict,
    call: Callable[[Provider, dict], Any],
    notify: Callable[[str], None] = lambda m: None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, Provider]:
    """Run call(provider, provider_keys) on the chain. Returns (result, provider_used).

    Retries transient errors / rate limits with backoff (respecting Retry-After, capped);
    switches to the next free provider on persistent failure, with a visible Hindi notice;
    raises ProviderError('all_failed') when every option fails."""
    candidates = chain(capability, preferred_id, all_keys)
    if not candidates:
        raise ProviderError("all_failed", f"'{capability}' के लिए कोई provider उपलब्ध नहीं — Settings में key डालें।")
    errors: list[str] = []
    for idx, p in enumerate(candidates):
        if not p.has_keys(all_keys):
            errors.append(f"{p.label}: key नहीं")
            continue
        for attempt in range(1, MAX_ATTEMPTS_PER_PROVIDER + 1):
            try:
                try:
                    return call(p, p.keys_for(all_keys)), p
                except ProviderError:
                    raise
                except Exception as exc:  # unexpected adapter bug / malformed response
                    raise ProviderError("bad_output", f"{p.label}: अप्रत्याशित जवाब ({type(exc).__name__})")
            except ProviderError as e:
                retryable = e.kind in ("transient", "rate_limited") and attempt < MAX_ATTEMPTS_PER_PROVIDER
                if retryable:
                    wait = min(e.retry_after if e.retry_after else 2.0 * attempt, MAX_RETRY_WAIT_S)
                    notify(f"{p.label}: अस्थायी समस्या, {wait:.0f} सेकंड बाद फिर कोशिश ({e.kind})।")
                    sleep(wait)
                    continue
                errors.append(f"{p.label}: {e}")
                nxt = next((q for q in candidates[idx + 1:] if q.has_keys(all_keys)), None)
                if nxt is not None:
                    reason = "की limit पूरी हुई" if e.kind == "rate_limited" else "काम नहीं कर रहा"
                    notify(f"{p.label} {reason}, {nxt.label} पर switch किया।")
                break
    raise ProviderError("all_failed", "सभी providers विफल रहे: " + " | ".join(errors))
