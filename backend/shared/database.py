"""MongoDB connection.

Tries a real MongoDB server (via the MONGO_URI env var) and transparently falls
back to an in-memory, pymongo-compatible store (mongomock) when none is
reachable. All the rest of the backend is written against the standard pymongo
collection API, so switching to a real MongoDB later is just setting MONGO_URI —
no code changes. NOTE: with the in-memory fallback, data resets on restart.
"""

from __future__ import annotations

import functools
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
                    # Fail FAST, do not hang. These are reached only when the
                    # connection is already broken, and every second spent
                    # waiting is a second the whole API is frozen: pymongo is
                    # synchronous, so a stalled call blocks FastAPI's event
                    # loop and even the login page stops loading.
                    #
                    # Atlas drops idle SSL connections ("EOF occurred in
                    # violation of protocol"); at 20s the app looked dead for
                    # 20s each time. 5s is long enough for a real reconnect
                    # on a slow link and short enough to stay usable.
                    # On 2026-11-16 at 11:00 UTC Atlas stopped answering for a
                    # few minutes (Errno 110 on the TLS handshake). The app
                    # stayed frozen for TWENTY-FOUR HOURS and needed a manual
                    # restart. The outage was Atlas's; the 24 hours were ours.
                    #
                    # Why a short blip became a day of downtime: pymongo is
                    # synchronous, so a call that never returns pins the
                    # FastAPI event loop, and the loop serves every request.
                    # Once pinned, nothing else runs — not the next request,
                    # not /health (which touches no database at all), and not
                    # the code that would have noticed Atlas was back. The old
                    # socketTimeoutMS=20000 meant each stalled call held the
                    # whole app for 20s, and retryReads doubled that to 40s
                    # per call. Under the ~200 calls a lead hunt makes, the app
                    # was effectively frozen for as long as Atlas stayed away.
                    #
                    # 8s is the ceiling now: slow enough for a genuine
                    # reconnect over a long link to Mumbai, short enough that a
                    # stall is a visible hiccup instead of an outage.
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=8000,
                    maxPoolSize=50,
                    # minPoolSize was 5. Keeping warm sockets means a
                    # background thread maintaining them, and that thread is
                    # what raised the 11:00 NetworkTimeout: it kept trying to
                    # re-establish sockets to an Atlas that was not answering.
                    # Warm sockets save ~200ms on the first call after an idle
                    # spell; they are not worth owning a thread that fails
                    # loudly during exactly the outage we need to survive.
                    minPoolSize=0,
                    maxIdleTimeMS=300000,
                    # retryReads/Writes are kept: a ONE-off dropped socket is
                    # the common case and a silent retry is right for it. With
                    # socketTimeoutMS at 8s the worst case is now ~16s rather
                    # than the old 40s, and bounded is the property that
                    # matters.
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


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
# Bounding each call at 8s is necessary but not sufficient. A lead hunt makes
# roughly 200 database calls, so an Atlas outage still costs 200 x 8s = ~27
# minutes of a frozen event loop, and the next hunt starts the clock again.
# That is the mechanism that turned a few minutes of Atlas trouble into a day
# of downtime on 2026-11-16.
#
# So after a few consecutive timeouts we stop asking. While the breaker is
# OPEN every call fails instantly with DatabaseUnavailable instead of pinning
# the loop for 8s, which keeps the app responsive enough to serve /health, the
# login page and a clear error message. One probe is allowed through every
# _BREAKER_RETRY_AFTER seconds; the first success closes the breaker and normal
# service resumes with no restart and no human involved.
#
# The failure modes are deliberately asymmetric: a tripped breaker during a
# healthy spell costs a handful of failed requests, while a breaker that never
# trips costs hours of total outage. We have now paid the second price once.

_BREAKER_THRESHOLD = 3        # consecutive timeouts before we stop asking
_BREAKER_RETRY_AFTER = 10.0   # seconds before a single probe is let through

_breaker_failures = 0
_breaker_opened_at: float | None = None


class DatabaseUnavailable(Exception):
    """The database is not answering and the breaker is open.

    Raised instead of blocking. Callers should treat this as "try again in a
    moment", never as "the data is gone" — nothing has been lost, the store is
    simply unreachable right now.
    """


def _is_timeout(exc: BaseException) -> bool:
    """Is this exception Mongo being unreachable, rather than a real error?

    Only connection-level faults should move the breaker. A duplicate-key or
    validation error means Mongo answered us perfectly well and must not count
    towards tripping it.
    """
    try:
        from pymongo.errors import (ConnectionFailure, ExecutionTimeout,
                                    NetworkTimeout, ServerSelectionTimeoutError,
                                    WaitQueueTimeoutError)
        timeouts = (ServerSelectionTimeoutError, NetworkTimeout, ConnectionFailure,
                    WaitQueueTimeoutError, ExecutionTimeout)
    except Exception:  # noqa: BLE001 - pymongo absent (mongomock-only runs)
        timeouts = ()
    return isinstance(exc, timeouts) or isinstance(exc, (TimeoutError, OSError))


def _breaker_check() -> None:
    """Fail immediately if the breaker is open, except for a periodic probe."""
    global _breaker_failures, _breaker_opened_at
    if _breaker_opened_at is None:
        return
    import time
    waited = time.monotonic() - _breaker_opened_at
    if waited < _BREAKER_RETRY_AFTER:
        raise DatabaseUnavailable(
            f"The database is not responding (retrying in "
            f"{_BREAKER_RETRY_AFTER - waited:.0f}s). Nothing has been lost — "
            f"please try again shortly.")
    # Probe window: let this one call through and see what happens.
    log.info("Database breaker: probing after %.0fs", waited)
    _breaker_opened_at = time.monotonic()   # re-arm so only ONE probe gets through


def _breaker_record(exc: BaseException | None) -> None:
    """Update breaker state from a call's outcome."""
    global _breaker_failures, _breaker_opened_at
    import time
    if exc is None:
        if _breaker_opened_at is not None:
            log.info("Database breaker CLOSED — Mongo is answering again")
        _breaker_failures = 0
        _breaker_opened_at = None
        return
    if not _is_timeout(exc):
        return                              # a real error, not a connectivity one
    _breaker_failures += 1
    if _breaker_failures >= _BREAKER_THRESHOLD and _breaker_opened_at is None:
        _breaker_opened_at = time.monotonic()
        log.error("=" * 78)
        log.error("Database breaker OPEN after %d consecutive timeouts.", _breaker_failures)
        log.error("Requests now fail FAST instead of freezing the app. Your data is")
        log.error("intact; this clears itself as soon as Mongo answers again.")
        log.error("Last error: %s", str(exc)[:200])
        log.error("=" * 78)


def breaker_state() -> dict:
    """For /health and the IT monitor: is the database currently usable?"""
    return {"open": _breaker_opened_at is not None, "failures": _breaker_failures}


def _is_cursor(obj) -> bool:
    """Is this a lazy pymongo cursor rather than a finished result?"""
    try:
        from pymongo.command_cursor import CommandCursor
        from pymongo.cursor import Cursor
        return isinstance(obj, (Cursor, CommandCursor))
    except Exception:  # noqa: BLE001 - pymongo absent
        return False


class _GuardedCursor:
    """A pymongo cursor that keeps its chaining but reports to the breaker.

    `find()` returns a cursor without contacting the server; the query runs on
    first iteration. So a timeout happens *after* find() returned, which is
    exactly the call shape this app uses most and the one the breaker most
    needs to see.

    Chaining must survive: `find(q).sort("created_at", -1).limit(40)` appears
    nine times in this codebase, including the leads list and notifications.
    So `.sort()`, `.limit()` and friends return another guarded cursor rather
    than a plain list, and only iteration talks to Mongo.
    """

    __slots__ = ("_cur",)

    # Methods that refine a query and hand back the cursor for more chaining.
    _CHAINING = frozenset({
        "sort", "limit", "skip", "batch_size", "max_time_ms", "hint",
        "collation", "comment", "allow_disk_use", "min", "max", "where",
        "add_option", "remove_option", "rewind",
    })

    def __init__(self, cur):
        self._cur = cur

    def __iter__(self):
        # The query actually runs here, so this is where the breaker watches.
        _breaker_check()
        try:
            items = list(self._cur)
        except Exception as exc:  # noqa: BLE001
            _breaker_record(exc)
            raise
        _breaker_record(None)
        return iter(items)

    def __next__(self):
        _breaker_check()
        try:
            item = next(self._cur)
        except StopIteration:
            _breaker_record(None)
            raise
        except Exception as exc:  # noqa: BLE001
            _breaker_record(exc)
            raise
        _breaker_record(None)
        return item

    def __getitem__(self, item):
        _breaker_check()
        try:
            result = self._cur[item]
        except Exception as exc:  # noqa: BLE001
            _breaker_record(exc)
            raise
        _breaker_record(None)
        return _GuardedCursor(result) if _is_cursor(result) else result

    def __getattr__(self, item):
        attr = getattr(self._cur, item)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        def guarded(*args, **kwargs):
            if item in self._CHAINING:
                # Pure query-building: no network, so no breaker involvement.
                # Re-wrap so the next link in the chain stays guarded too.
                result = attr(*args, **kwargs)
                return _GuardedCursor(result) if _is_cursor(result) else result
            _breaker_check()
            try:
                result = attr(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                _breaker_record(exc)
                raise
            _breaker_record(None)
            return _GuardedCursor(result) if _is_cursor(result) else result

        return guarded


class _GuardedCollection:
    """A pymongo Collection that honours the breaker.

    Every data method is wrapped so a connectivity failure trips the breaker
    and a success resets it. Anything that is not a callable (and `name`,
    `database`, …) passes straight through untouched.
    """

    __slots__ = ("_col",)

    def __init__(self, col):
        self._col = col

    def __getattr__(self, item):
        attr = getattr(self._col, item)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        def guarded(*args, **kwargs):
            _breaker_check()
            try:
                result = attr(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised after recording
                _breaker_record(exc)
                raise
            # A cursor is lazy: find() has not talked to Mongo yet, so a
            # timeout would strike later, during iteration, and never reach the
            # breaker. It must therefore be wrapped — but NOT resolved to a
            # list here, because the codebase chains on it in nine places
            # (`find(q).sort(...).limit(n)`), and a list has no .sort(). An
            # earlier version of this guard did flatten it, which would have
            # broken the leads page and notifications on deploy.
            if _is_cursor(result):
                return _GuardedCursor(result)
            _breaker_record(None)
            return result

        return guarded

    def __getitem__(self, item):
        return _GuardedCollection(self._col[item])


class _GuardedDB:
    """A pymongo Database whose collections carry the breaker."""

    __slots__ = ("_wrapped",)

    def __init__(self, db):
        self._wrapped = db

    def __getitem__(self, name):
        return _GuardedCollection(self._wrapped[name])

    def __getattr__(self, item):
        attr = getattr(self._wrapped, item)
        if callable(attr):

            @functools.wraps(attr)
            def guarded(*args, **kwargs):
                _breaker_check()
                try:
                    result = attr(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    _breaker_record(exc)
                    raise
                _breaker_record(None)
                return result

            return guarded
        return attr


def get_db():
    if _db is None:
        _connect()
    # mongomock is in-process and cannot time out, so it needs no guard and
    # the tests keep working against a plain handle.
    if _backend == "mongomock":
        return _db
    return _GuardedDB(_db)


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
