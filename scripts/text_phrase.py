#!/usr/bin/env python3
"""Format city copy as complete phrases (no mid-sentence ellipsis)."""

from __future__ import annotations

import re

_INCOMPLETE_TAIL = re.compile(
    r"\b(?:a|an|the|and|or|with|in|on|at|to|for|of|by|as|its|their|is|are|was|were|a)\.$",
    re.I,
)
_HANGING_PHRASE = re.compile(
    r"\b(?:its|the|a|an|their|this|that|with|and|or)\s+[\w'-]+\.$",
    re.I,
)
_BROKEN_UNIT = re.compile(r"\d[\d,]*\s+[a-z]{1,3}\.$", re.I)
_BROKEN_GENERAL = re.compile(r"…|" + _BROKEN_UNIT.pattern, re.I)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", _clean(text))
    return [p.strip() for p in parts if len(p.strip()) > 20]


def is_broken_copy(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _BROKEN_GENERAL.search(t):
        return True
    if len(t) > 48 and t[-1] not in ".!?":
        return True
    if re.search(r"\b(?:Provin|municip|kilomet|populat|capit|describ)\s*$", t, re.I):
        return True
    return False


def summary_paragraph(text: str, max_len: int = 420) -> str:
    """City intro: whole sentences only, up to max_len."""
    t = _clean(text)
    if not t:
        return ""
    parts = sentences(t)
    if not parts:
        return complete_phrase(t, max_len)

    chosen: list[str] = []
    total = 0
    for part in parts:
        piece = part if part[-1] in ".!?" else _finish(part)
        add = len(piece) + (1 if chosen else 0)
        if total + add > max_len:
            if chosen:
                break
            return complete_phrase(piece, max_len)
        if _is_complete(piece, min_len=12) or not chosen:
            chosen.append(piece)
            total += add
        if total >= max_len - 40:
            break
    joined = " ".join(chosen).strip()
    return joined if joined and not is_broken_copy(joined) else complete_phrase(t, max_len)


def _clean(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if t.endswith("…"):
        t = t[:-1].rstrip(" ,;—")
    return t


def _finish(text: str) -> str:
    t = text.strip().rstrip(" ,;—")
    if not t:
        return ""
    if t[-1] in ".!?":
        return t
    return f"{t}."


def _is_complete(line: str, *, min_len: int = 24) -> bool:
    if len(line) < min_len:
        return False
    if (
        _INCOMPLETE_TAIL.search(line)
        or _HANGING_PHRASE.search(line)
        or _BROKEN_UNIT.search(line)
    ):
        return False
    if re.search(r"\b(?:with|and|or|the|a|an|in|on|at|to|for|of)\s*$", line, re.I):
        return False
    return True


def highlight_line(text: str, max_len: int = 120) -> str:
    """Highlight bullet: keep only if the whole sentence fits."""
    t = _clean(text)
    if not t:
        return ""
    if len(t) <= max_len:
        line = _finish(t)
        return line if _is_complete(line) else ""
    return ""


def complete_phrase(text: str, max_len: int = 120) -> str:
    """Taglines / summaries: end at sentence or word boundary, never with …"""
    t = _clean(text)
    if not t:
        return ""
    if len(t) <= max_len:
        line = _finish(t)
        return line if _is_complete(line, min_len=12) else line

    window = t[:max_len]
    for sep in (". ", "! ", "? "):
        idx = window.rfind(sep)
        if idx >= int(max_len * 0.45):
            line = _finish(t[: idx + 1])
            if _is_complete(line, min_len=12):
                return line

    idx = window.rfind(" ")
    if idx >= 40:
        line = _finish(t[:idx])
        if _is_complete(line, min_len=12):
            return line

    return _finish(window.rstrip(" ,;—")) if len(window) >= 40 else ""
