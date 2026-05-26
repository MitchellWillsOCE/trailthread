#!/usr/bin/env python3
"""Add short taglines to place-details.json from activities or general text."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETAILS_PATH = ROOT / "Trip" / "place-details.json"


def make_tagline(entry: dict) -> str:
    if entry.get("tagline"):
        return entry["tagline"]
    activities = entry.get("activities") or []
    if activities:
        return activities[0]
    text = (entry.get("general") or "").strip()
    if not text:
        return ""
    if len(text) <= 72:
        return text
    cut = text[:72]
    last_space = cut.rfind(" ")
    end = last_space if last_space > 40 else 72
    return f"{cut[:end].strip()}…"


def main() -> None:
    data = json.loads(DETAILS_PATH.read_text(encoding="utf-8"))
    updated = 0
    for name, entry in data.items():
        tagline = make_tagline(entry)
        if not tagline:
            continue
        if entry.get("tagline") != tagline:
            entry["tagline"] = tagline
            updated += 1
    DETAILS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated taglines for {updated} places ({len(data)} total).")


if __name__ == "__main__":
    main()
