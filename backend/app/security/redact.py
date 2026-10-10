"""Log redaction: scrubs every provider key value this process has seen, plus common
key-shaped tokens, from all log records (PRD §6.5, §12.2)."""

import logging
import re

from .keys import known_secrets

_NAMED = re.compile(r"(?i)\b(x-provider-keys|authorization|api[-_]?key|x-goog-api-key|key)(\s*[:=]\s*)(?:Bearer\s+)?[^\s&\"',}]+")
_TOKENS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
]


def redact(text: str) -> str:
    for secret in known_secrets():
        if secret in text:
            text = text.replace(secret, "[REDACTED]")
    text = _NAMED.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    for pat in _TOKENS:
        text = pat.sub("[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg = clean
            record.args = ()
        return True


def install() -> None:
    f = RedactingFilter()
    root = logging.getLogger()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        lg = logging.getLogger(name)
        if not any(isinstance(x, RedactingFilter) for x in lg.filters):
            lg.addFilter(f)
    for h in root.handlers:
        if not any(isinstance(x, RedactingFilter) for x in h.filters):
            h.addFilter(f)
