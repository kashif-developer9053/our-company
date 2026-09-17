"""MongoDB connection.

Tries a real MongoDB server (via the MONGO_URI env var) and transparently falls
back to an in-memory, pymongo-compatible store (mongomock) when none is
reachable. All the rest of the backend is written against the standard pymongo
collection API, so switching to a real MongoDB later is just setting MONGO_URI —
no code changes. NOTE: with the in-memory fallback, data resets on restart.
"""

from __future__ import annotations

import os

from .logger import get_logger

log = get_logger("database")

_db = None
_backend: str | None = None


def _use_public_dns() -> None:
    """Resolve mongodb+srv:// via public DNS.

    Some home routers fail SRV/TXT lookups, which makes Atlas unreachable and
    silently drops the app onto the empty in-memory store. Point pymongo's
    resolver at public servers so a flaky router can't cost us the real data.
    """
    try:
        import dns.resolver

        # pymongo calls dns.resolver.resolve(), which uses this default resolver.
        # Put public DNS FIRST so a broken router is bypassed, not merely appended.
        override = dns.resolver.Resolver(configure=True)
        router_ns = [ns for ns in override.nameservers if ns not in ("8.8.8.8", "1.1.1.1")]
        override.nameservers = ["8.8.8.8", "1.1.1.1", *router_ns]
        override.timeout = 5.0
        override.lifetime = 15.0
        dns.resolver.default_resolver = override
        log.info("DNS: using public resolvers first for mongodb+srv lookup")
    except Exception as exc:  # noqa: BLE001 - best effort only
        log.debug("Could not install public DNS resolver: %s", exc)


def _connect() -> None:
    global _db, _backend
    uri = os.environ.get("MONGO_URI")
    if uri:
        if uri.startswith("mongodb+srv://"):
            _use_public_dns()
        last_error = ""
        # Retry: a cold DNS/SRV lookup regularly needs more than one attempt.
        for attempt in (1, 2, 3):
            try:
                from pymongo import MongoClient

                # A pooled client: connections are reused across requests, so
                # only the first call pays the DNS/TLS handshake cost.
                # compressors cut transfer size, which matters on a slow link.
                client = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=20000,
                    connectTimeoutMS=20000,
                    socketTimeoutMS=60000,
                    maxPoolSize=50,
                    minPoolSize=5,          # keep warm sockets ready
                    maxIdleTimeMS=300000,
                    retryReads=True,
                    retryWrites=True,
                    compressors="zstd,snappy,zlib",
                )
                client.admin.command("ping")
                _db = client["ai_agency"]
                _backend = "mongodb"
                log.info("Connected to real MongoDB at MONGO_URI")
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                log.warning("MongoDB connect attempt %d/3 failed: %s", attempt, last_error[:160])

        # Falling back loses access to the REAL data — make that impossible to miss.
        if os.environ.get("REQUIRE_MONGO", "").lower() in ("1", "true", "yes"):
            raise RuntimeError(
                f"MONGO_URI is set but unreachable and REQUIRE_MONGO is on. Refusing to start "
                f"with an empty in-memory database. Last error: {last_error[:300]}")
        log.error("=" * 78)
        log.error("MONGO_URI IS SET BUT UNREACHABLE — falling back to EMPTY in-memory storage.")
        log.error("Your real leads/users are NOT here. Seed data and the admin-setup screen")
        log.error("you see now are fake. Fix the connection, then restart — nothing was lost.")
        log.error("Cause: %s", last_error[:300])
        log.error("=" * 78)

    import mongomock

    client = mongomock.MongoClient()
    _db = client["ai_agency"]
    _backend = "mongomock"
    log.info("Using in-memory MongoDB (mongomock) — data resets on restart")


def get_db():
    if _db is None:
        _connect()
    return _db


def backend_name() -> str:
    if _backend is None:
        _connect()
    return _backend or "unknown"


# Indexes the app depends on. `email_drafts` had none at all, so every mailbox
# open ran full collection scans — and with Atlas ~240ms away, each of those
# round trips is expensive. Created on startup and idempotent: MongoDB ignores
# a create_index call for an index that already exists.
_INDEXES: dict[str, list] = {
    "email_drafts": [
        ([("status", 1)], {}),
        ([("lead_id", 1)], {}),
        ([("batch_id", 1)], {}),
        ([("id", 1)], {"unique": True}),
        ([("status", 1), ("created_at", -1)], {}),
    ],
    "leads": [
        ([("do_not_email", 1)], {}),
        ([("niche", 1)], {}),
        ([("city", 1)], {}),
        ([("outreach_history.type", 1)], {}),
        ([("status", 1), ("email", 1)], {}),
    ],
    "email_events": [([("email", 1)], {}), ([("at", -1)], {})],
    "suppressed": [([("reason", 1)], {})],
    "health_checks": [([("created_at", -1)], {})],
    "activity_events": [([("created_at", -1)], {})],
}


def ensure_indexes() -> dict:
    """Create the indexes the app relies on. Never raises — a missing index
    makes things slow, but failing to start makes them unusable."""
    created, failed = 0, 0
    db = get_db()
    for collection, specs in _INDEXES.items():
        for keys, opts in specs:
            try:
                db[collection].create_index(keys, background=True, **opts)
                created += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.warning("Index on %s %s failed (isolated): %s", collection, keys, exc)
    log.info("Index check complete: %d ensured, %d failed.", created, failed)
    return {"ensured": created, "failed": failed}
