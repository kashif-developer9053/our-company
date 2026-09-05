"""Niche suggestion model + parsing of Claude's response.

Supports two response shapes:
  - a bare JSON array of niches (when the CEO supplied industry + country), and
  - a JSON object {industry, country, selection_reasoning, niches:[...]} (when
    Agent 1 self-selected the industry and/or country).
"""

from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel, Field


class NicheRequest(BaseModel):
    # All optional now: blank fields => Agent 1 self-selects.
    industry: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)


def serialize(doc: dict) -> dict:
    return {
        "id": doc["id"],
        # `industry`/`country`/`city` hold the values actually USED (provided or
        # self-picked). Aliases *_used are included for clarity.
        "industry": doc.get("industry", ""),
        "country": doc.get("country", ""),
        "city": doc.get("city", ""),
        "industry_used": doc.get("industry", ""),
        "country_used": doc.get("country", ""),
        "city_used": doc.get("city", "") or None,
        "selection_reasoning": doc.get("selection_reasoning") or None,
        "niches": doc.get("niches", []),
        "status": doc.get("status", ""),
        "supervisor_note": doc.get("supervisor_note", ""),
        "approved_niche": doc.get("approved_niche", ""),
        "created_at": doc.get("created_at", ""),
    }


def _load_json(text: str):
    """Best-effort extract the first JSON value (object or array) from text."""
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    # 1) Try to parse a complete, balanced JSON array anywhere in the text.
    depth = 0
    start_idx = -1
    for i, ch in enumerate(cleaned):
        if ch == "[":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "]" and depth > 0:
            depth -= 1
            if depth == 0 and start_idx != -1:
                try:
                    return json.loads(cleaned[start_idx:i + 1])
                except Exception:  # noqa: BLE001
                    pass
    # 2) Salvage every COMPLETE {...} object (handles a truncated array). If there
    #    are several, return them as a list; a single one is returned as a dict.
    objs = []
    depth = 0
    obj_start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and obj_start != -1:
                try:
                    objs.append(json.loads(cleaned[obj_start:i + 1]))
                except Exception:  # noqa: BLE001
                    pass
    if len(objs) > 1:
        return objs
    if len(objs) == 1:
        return objs[0]
    return None


def _normalize_niches(raw) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            name = item.get("niche_name") or item.get("name") or ""
            reason = item.get("reasoning") or item.get("why") or item.get("reason") or ""
            if name:
                out.append({"niche_name": str(name).strip(), "reasoning": str(reason).strip()})
    return out[:4]


def parse_niches(text: str) -> list[dict]:
    """Parse just the niche list (used when the CEO supplied industry+country)."""
    data = _load_json(text)
    if isinstance(data, dict):
        data = data.get("niches") or data.get("suggestions") or []
    return _normalize_niches(data if isinstance(data, list) else [])


def parse_result(text: str) -> dict:
    """Parse a self-select response: object with industry/country/reasoning/niches,
    or (fallback) a bare niche array."""
    data = _load_json(text)
    industry = country = reasoning = None
    niches: list[dict] = []
    if isinstance(data, dict):
        industry = data.get("industry") or data.get("industry_used")
        country = data.get("country") or data.get("country_used")
        reasoning = data.get("selection_reasoning") or data.get("reasoning")
        niches = _normalize_niches(data.get("niches") or data.get("suggestions") or [])
    elif isinstance(data, list):
        niches = _normalize_niches(data)
    return {
        "industry": str(industry).strip() if industry else None,
        "country": str(country).strip() if country else None,
        "selection_reasoning": str(reasoning).strip() if reasoning else None,
        "niches": niches,
    }
