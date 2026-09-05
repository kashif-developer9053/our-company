"""Knowledge base — uploaded files/text, scoped globally or to one agent, used as
grounding context. Files are text-extracted on upload (PDF/DOCX/TXT)."""

from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timezone

from .database import get_db
from .logger import get_logger

log = get_logger("knowledge_base")


def _col():
    return get_db()["knowledge_base"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_text(filename: str, data: bytes) -> str:
    """Extract text from a PDF/DOCX/TXT upload. Never raises."""
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        if name.endswith(".docx"):
            import docx
            d = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs).strip()
        return data.decode("utf-8", errors="replace").strip()  # txt / fallback
    except Exception as exc:  # noqa: BLE001
        log.error("Text extraction failed for %s: %s", filename, exc)
        return ""


def add_entry(title: str, content: str, content_type: str, scope: str, agent_id: str | None, original_filename: str | None) -> dict:
    entry = {
        "id": f"kb_{uuid.uuid4().hex[:8]}", "title": title, "content_type": content_type,
        "content": content, "original_filename": original_filename,
        "scope": scope if scope in ("global", "agent_specific") else "global",
        "agent_id": agent_id if scope == "agent_specific" else None,
        "uploaded_at": _now(),
    }
    _col().insert_one(dict(entry))
    return serialize(entry)


def serialize(doc: dict) -> dict:
    return {
        "id": doc["id"], "title": doc.get("title", ""), "content_type": doc.get("content_type", "text"),
        "scope": doc.get("scope", "global"), "agent_id": doc.get("agent_id"),
        "original_filename": doc.get("original_filename"),
        "chars": len(doc.get("content", "")), "uploaded_at": doc.get("uploaded_at", ""),
    }


def list_entries() -> list[dict]:
    docs = list(_col().find({}))
    docs.sort(key=lambda d: d.get("uploaded_at", ""), reverse=True)
    return [serialize(d) for d in docs]


def delete_entry(entry_id: str) -> None:
    _col().delete_one({"id": entry_id})


def _score(text: str, query: str) -> int:
    """Simple keyword-overlap relevance (no embeddings needed)."""
    words = {w for w in re.findall(r"[a-z0-9]{4,}", query.lower())}
    if not words:
        return 1  # no query -> everything mildly relevant
    tl = text.lower()
    return sum(tl.count(w) for w in words)


def relevant_context(agent_id: str, query: str, max_entries: int = 3, max_chars: int = 2500) -> str:
    """Return the most relevant KB content for this agent: all global entries +
    this agent's own, ranked by keyword overlap with the current task, top N.
    Keeps context small so token cost stays bounded even as the KB grows."""
    candidates = list(_col().find({"$or": [{"scope": "global"}, {"agent_id": agent_id}]}))
    if not candidates:
        return ""
    ranked = sorted(candidates, key=lambda d: _score(d.get("content", ""), query), reverse=True)
    picked, out, used = [], [], 0
    for d in ranked[:max_entries]:
        snippet = d.get("content", "")[:max_chars - used]
        if not snippet:
            break
        out.append(f"[{d.get('title')}]\n{snippet}")
        used += len(snippet)
        picked.append(d["id"])
        if used >= max_chars:
            break
    return "\n\n".join(out)
