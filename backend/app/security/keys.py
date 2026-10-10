"""Provider keys travel from the browser in the X-Provider-Keys header (base64 JSON:
{provider_id: {key_name: value}}). They are held in memory only — never written to
disk, the DB, logs, job records or error messages (PRD §6.5)."""

import base64
import json
import threading

from fastapi import HTTPException, Request

HEADER = "x-provider-keys"

# Every key value seen by this process is registered here so log redaction can
# scrub it even if some library echoes it back in an error message.
_known_secrets: set[str] = set()
_known_lock = threading.Lock()

ProviderKeys = dict[str, dict[str, str]]


def register_secrets(keys: ProviderKeys) -> None:
    with _known_lock:
        for fields in keys.values():
            for v in fields.values():
                if isinstance(v, str) and len(v) >= 6:
                    _known_secrets.add(v)


def known_secrets() -> list[str]:
    with _known_lock:
        return sorted(_known_secrets, key=len, reverse=True)


def parse_keys_header(raw: str | None) -> ProviderKeys:
    if not raw:
        return {}
    try:
        data = json.loads(base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail={"code": "bad_keys_header", "message": "X-Provider-Keys हेडर पढ़ा नहीं जा सका।"})
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail={"code": "bad_keys_header", "message": "X-Provider-Keys हेडर ग़लत है।"})
    out: ProviderKeys = {}
    for pid, fields in data.items():
        if isinstance(pid, str) and isinstance(fields, dict):
            clean = {str(k): str(v).strip() for k, v in fields.items() if isinstance(v, str) and v.strip()}
            if clean:
                out[pid] = clean
    register_secrets(out)
    return out


def keys_from_request(request: Request) -> ProviderKeys:
    return parse_keys_header(request.headers.get(HEADER))


def encode_keys_header(keys: ProviderKeys) -> str:
    """Helper for tests / internal callers."""
    return base64.b64encode(json.dumps(keys).encode("utf-8")).decode("ascii")
