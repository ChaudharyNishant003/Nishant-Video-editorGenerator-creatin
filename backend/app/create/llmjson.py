"""Ask an LLM for JSON, validate it, repair once on the same provider, then fall back to the next free
LLM through the registry (PRD §5.4, §6.6). LLM output is always untrusted."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from ..edit.planner import extract_json
from ..providers import registry
from ..providers.base import ProviderError

T = TypeVar("T")


def ask_json(system: str, user: str, validate: Callable[[dict], T], all_keys: dict, preferred: str | None,
             notify: Callable[[str], None], check_cancel: Callable[[], None] = lambda: None) -> tuple[T, str]:
    """Returns (validated result, provider label). Raises ProviderError('all_failed') when no LLM works."""

    def call(p, keys):
        check_cancel()
        text = p.impl(system, user, keys, json_mode=True)
        try:
            return validate(extract_json(text))
        except ValueError as first:  # JSONDecodeError, pydantic ValidationError and ScriptError are ValueErrors
            notify(f"{p.label}: जवाब सही JSON नहीं था, सुधार के लिए फिर पूछा।")
            check_cancel()
            fix = p.impl(system, user + f"\n\nYOUR PREVIOUS REPLY WAS INVALID ({str(first)[:200]}). "
                         f"Previous reply:\n{text[:3000]}\n\nReturn ONLY the corrected JSON object.", keys, json_mode=True)
            try:
                return validate(extract_json(fix))
            except ValueError:
                raise ProviderError("bad_output", "दो बार अमान्य जवाब मिला।")

    result, provider = registry.run_with_fallback("llm", preferred, all_keys, call, notify=notify)
    return result, provider.label


def has_llm(all_keys: dict) -> bool:
    return bool(registry.chain("llm", None, all_keys))


def as_text(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]
