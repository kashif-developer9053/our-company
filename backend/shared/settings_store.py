"""Read a stored (encrypted) setting value, decrypting in-memory at call time.

Used by the mailer + agents. Same rule as the Claude key: decryption happens
only here, never logged, never returned by any public API in full.
"""

from __future__ import annotations

from .database import get_db
from .logger import get_logger
from .security import decrypt

log = get_logger("settings_store")


def get_setting_value(key_name: str) -> str | None:
    doc = get_db()["settings"].find_one({"key_name": key_name})
    if doc and doc.get("encrypted_value"):
        try:
            return decrypt(doc["encrypted_value"])
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to decrypt '%s' (wrong ENCRYPTION_SECRET?): %s", key_name, exc)
            return None
    return None


def get_config() -> dict:
    """Non-secret config (e.g. daily send cap). Stored as a singleton doc."""
    doc = get_db()["config"].find_one({"_id": "singleton"})
    if doc is None:
        doc = {"_id": "singleton", "daily_send_cap": 25}
        get_db()["config"].insert_one(dict(doc))
    return {"daily_send_cap": int(doc.get("daily_send_cap", 25))}


def set_config(daily_send_cap: int) -> dict:
    get_db()["config"].update_one({"_id": "singleton"}, {"$set": {"daily_send_cap": int(daily_send_cap)}}, upsert=True)
    return get_config()
