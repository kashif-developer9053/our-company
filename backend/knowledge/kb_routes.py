"""Knowledge Base API (admin-only via router dependency). Upload files (PDF/DOCX/
TXT) or paste text, scoped globally or to a specific agent."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from shared import knowledge_base as kb
from shared.safe_wrapper import safe_endpoint

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("")
@safe_endpoint("knowledge")
async def list_kb():
    return {"ok": True, "entries": kb.list_entries()}


class TextEntry(BaseModel):
    title: str
    content: str
    scope: str = "global"
    agent_id: str | None = None


@router.post("/text")
@safe_endpoint("knowledge")
async def add_text(body: TextEntry):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Empty content")
    entry = kb.add_entry(body.title.strip() or "Untitled", body.content.strip(), "text", body.scope, body.agent_id, None)
    return {"ok": True, "entry": entry}


@router.post("/upload")
@safe_endpoint("knowledge")
async def upload(file: UploadFile = File(...), scope: str = Form("global"), agent_id: str = Form(""), title: str = Form("")):
    data = await file.read()
    text = kb.extract_text(file.filename or "", data)
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract any text from that file.")
    entry = kb.add_entry(title.strip() or (file.filename or "Untitled"), text, "file", scope, agent_id or None, file.filename)
    return {"ok": True, "entry": entry, "extracted_chars": len(text)}


@router.delete("/{entry_id}")
@safe_endpoint("knowledge")
async def delete_kb(entry_id: str):
    kb.delete_entry(entry_id)
    return {"ok": True, "deleted": entry_id}
