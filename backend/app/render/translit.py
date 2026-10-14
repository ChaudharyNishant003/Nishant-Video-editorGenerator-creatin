"""Devanagari → Roman Hinglish, rule-based (fallback for the 'Roman Hinglish' caption option when no LLM
key is available). Hinglish-style spelling: long vowels are written short (राजा → raja, पानी → pani),
inherent 'a' is dropped at word end and in the usual VC_CV position (रखना → rakhna, समझना → samajhna).
Imperfect by nature; the LLM transliteration is preferred when a key exists.
"""

from __future__ import annotations

import re

CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f", "य़": "y",
}
NUKTA_FORMS = {"क": "क़", "ख": "ख़", "ग": "ग़", "ज": "ज़", "ड": "ड़", "ढ": "ढ़", "फ": "फ़", "य": "य़"}
VOWELS = {"अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai",
          "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"}
MATRAS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
          "ॉ": "o", "ॅ": "e"}
VIRAMA, ANUSVARA, CHANDRA, VISARGA, NUKTA = "्", "ं", "ँ", "ः", "़"
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
COMMON = {
    "में": "mein", "हैं": "hain", "है": "hai", "नहीं": "nahi", "यह": "yeh", "वह": "woh", "मैं": "main", "क्या": "kya",
    "और": "aur", "भी": "bhi", "हम": "hum", "तुम": "tum", "कि": "ki", "की": "ki", "के": "ke", "को": "ko", "से": "se",
    "पर": "par", "था": "tha", "थी": "thi", "थे": "the", "हो": "ho", "एक": "ek", "ये": "ye", "वो": "wo", "आप": "aap",
    "यहाँ": "yahan", "वहाँ": "wahan", "कहाँ": "kahan", "क्यों": "kyon", "हाँ": "haan", "जी": "ji",
}
_DEV = re.compile(r"[ऀ-ॿ]+")


def _units(word: str) -> list[dict]:
    """Split into units: {'c': consonant roman or None, 'v': vowel roman or None (None = inherent),
    'virama': bool, 'nasal': str}."""
    units: list[dict] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if i + 1 < len(word) and word[i + 1] == NUKTA and ch in NUKTA_FORMS:
            ch = NUKTA_FORMS[ch]
            i += 1
        if ch in CONS:
            units.append({"c": CONS[ch], "v": None, "virama": False, "nasal": ""})
        elif ch in VOWELS:
            units.append({"c": None, "v": VOWELS[ch], "virama": False, "nasal": ""})
        elif ch in MATRAS and units and units[-1]["c"] is not None and units[-1]["v"] is None:
            units[-1]["v"] = MATRAS[ch]
        elif ch == VIRAMA and units:
            units[-1]["virama"] = True
        elif ch in (ANUSVARA, CHANDRA) and units:
            units[-1]["nasal"] = "n"
        elif ch == VISARGA and units:
            units[-1]["nasal"] += "h"
        elif ch in DIGITS:
            units.append({"c": None, "v": DIGITS[ch], "virama": False, "nasal": "", "lit": True})
        elif ch in ("।", "॥"):
            units.append({"c": None, "v": ".", "virama": False, "nasal": "", "lit": True})
        i += 1
    return units


def _word(word: str) -> str:
    if word in COMMON:
        return COMMON[word]
    u = _units(word)
    n = len(u)
    # schwa: consonant without matra and without virama has an inherent 'a' unless deleted
    keep = [x["c"] is not None and x["v"] is None and not x["virama"] for x in u]
    has_vowel = [x["v"] is not None or keep[k] for k, x in enumerate(u)]
    last_cons = max((k for k, x in enumerate(u) if x["c"] is not None), default=-1)
    for k in range(n - 1, -1, -1):
        if not keep[k]:
            continue
        x = u[k]
        if k == last_cons and k == n - 1 and not x["nasal"] and n > 1:
            prev_conjunct = k > 0 and u[k - 1]["virama"]
            ya_after_i = x["c"] == "y" and k > 0 and u[k - 1]["v"] == "i"   # क्षत्रिय → kshatriya
            if not prev_conjunct and not ya_after_i:
                keep[k] = has_vowel[k] = False
            continue
        if 0 < k < n - 1 and not x["nasal"]:
            # V C a C V → V C C V (रखना → rakhna); never after a nasal/cluster (परंपरा → parampara)
            prev, nxt = u[k - 1], u[k + 1]
            prev_open = has_vowel[k - 1] and not prev["nasal"] and not prev["virama"]
            next_voiced = nxt["c"] is not None and has_vowel[k + 1]
            if prev_open and next_voiced:
                keep[k] = has_vowel[k] = False
    out = []
    for k, x in enumerate(u):
        if x.get("lit"):
            out.append(x["v"])
            continue
        if x["c"]:
            out.append(x["c"])
        if x["v"] is not None:
            out.append(x["v"])
        elif keep[k]:
            out.append("a")
        nasal = x["nasal"]
        if nasal.startswith("n") and k + 1 < n and (u[k + 1]["c"] or "")[:1] in ("p", "b", "m"):
            nasal = "m" + nasal[1:]   # परंपरा → parampara
        out.append(nasal)
    return "".join(out)


def to_roman(text: str) -> str:
    """Transliterate every Devanagari run in text; other characters pass through."""
    return _DEV.sub(lambda m: _word(m.group(0)), text or "")
