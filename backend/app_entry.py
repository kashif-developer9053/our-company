"""FastAPI application entry point.

ONE app, modular folders. Each router (agents, crm, settings, status) is mounted
independently and every handler uses the safe-wrapper pattern, so a failure in
one module returns a clean isolated error and never takes down the others.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

# Windows + asyncio proactor logs a harmless "ConnectionResetError [WinError 10054]"
# traceback every time a browser drops a polling connection (the UI polls /status
# ~every 1.5s). The response has already been sent; only the socket shutdown fails.
# Swallow just that case so real errors stay visible.
if sys.platform == "win32":  # pragma: no cover - platform specific
    from asyncio.proactor_events import _ProactorBasePipeTransport

    def _silence_conn_reset(func):
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except (ConnectionResetError, ConnectionAbortedError):
                pass
        return wrapper

    _ProactorBasePipeTransport._call_connection_lost = _silence_conn_reset(
        _ProactorBasePipeTransport._call_connection_lost
    )

# Load backend/.env (ENCRYPTION_SECRET, optional MONGO_URI) before anything else.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402

from agent1.agent1_routes import router as agent1_router  # noqa: E402
from agent2.agent2_routes import router as agent2_router  # noqa: E402
from agent3.agent3_routes import router as agent3_router, run_reply_check  # noqa: E402
from agents.agent_registry import router as agents_router, seed_defaults  # noqa: E402
from auth.auth_routes import router as auth_router  # noqa: E402
from auth.deps import get_current_user, require_admin  # noqa: E402
from crm.leads_routes import router as leads_router, seed_leads  # noqa: E402
from it_monitor.it_monitor_routes import router as it_router, run_health_check  # noqa: E402
from knowledge.kb_routes import router as kb_router  # noqa: E402
from notifications.notifications_routes import router as notifications_router  # noqa: E402
from pipeline.pipeline_routes import router as pipeline_router  # noqa: E402
from shared.instructions import seed_instructions  # noqa: E402
from settings.settings_routes import router as settings_router  # noqa: E402
from shared.database import backend_name  # noqa: E402
from shared.logger import get_logger  # noqa: E402
from shared.safe_wrapper import safe_endpoint  # noqa: E402
from shared.security import encryption_secret_is_set  # noqa: E402
from shared.status_board import router as status_router  # noqa: E402
from supervisor.supervisor_routes import router as supervisor_router  # noqa: E402
from users.users_routes import router as users_router  # noqa: E402

log = get_logger("app")


async def _reply_check_loop():
    # Background IMAP reply-checking on an interval. Skips cleanly when email is
    # not configured or the connection fails; never crashes the app.
    import asyncio
    while True:
        await asyncio.sleep(720)  # every 12 minutes
        try:
            await run_reply_check()
        except Exception as exc:  # noqa: BLE001
            log.error("Reply-check loop error (isolated): %s", exc)


async def _health_check_loop():
    # IT Technician health monitoring on an interval. Fully isolated.
    import asyncio
    from datetime import datetime, timedelta, timezone
    while True:
        try:
            await run_health_check()
            # Weekly Supervisor strategic review (guarded so it runs ~once/week).
            from shared.database import get_db as _gdb
            from supervisor.supervisor_routes import run_strategic_review
            revs = list(_gdb()["strategic_reviews"].find({}))
            revs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
            stale = (not revs) or (revs[0].get("created_at", "") < (datetime.now(timezone.utc) - timedelta(days=7)).isoformat())
            if stale:
                await run_strategic_review()
        except Exception as exc:  # noqa: BLE001
            log.error("Health-check loop error (isolated): %s", exc)
        await asyncio.sleep(180)  # every 3 minutes


async def _followup_loop():
    """Draft follow-ups for leads that never replied, once every few hours.

    Drafting is the automated part; sending still needs approval. This exists
    because 30 of the first 37 cold emails never got a follow-up, and most cold
    outreach replies arrive on the second, third or fourth touch.
    """
    import asyncio
    from datetime import datetime, timezone
    # Give the app time to settle before the first pass.
    await asyncio.sleep(300)
    while True:
        try:
            from agent3.agent3_routes import _draft_followups_bg, _drafts
            from agent3.followup import due_leads
            from shared.database import get_db as _gdb

            # Do not pile drafts on top of an unreviewed queue — a backlog the
            # CEO has not approved means writing more helps nobody.
            pending = _drafts().count_documents({"status": "pending"})
            if pending >= 40:
                log.info("Follow-up pass skipped: %d drafts already pending review.", pending)
            else:
                targets = due_leads(_gdb()["leads"], limit=min(20, 40 - pending))
                if targets:
                    batch = f"FU-AUTO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
                    await _draft_followups_bg(targets, batch)
        except Exception as exc:  # noqa: BLE001
            log.error("Follow-up loop error (isolated): %s", exc)
        await asyncio.sleep(6 * 3600)  # every 6 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    # Seed default agents + leads + agent instructions on startup (idempotent).
    seed_defaults()
    seed_leads()
    seed_instructions()
    task = asyncio.create_task(_reply_check_loop())
    health_task = asyncio.create_task(_health_check_loop())
    followup_task = asyncio.create_task(_followup_loop())
    log.info(
        "Backend ready | storage=%s | encryption_secret_set=%s",
        backend_name(),
        encryption_secret_is_set(),
    )
    yield
    task.cancel()
    health_task.cancel()
    followup_task.cancel()


app = FastAPI(title="AI Agency Virtual Office — Backend", version="2.0", lifespan=lifespan)

# Compress responses — the lead list is a few hundred KB of JSON and this
# cuts it by ~80%, which is the difference on a slow connection.
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    # Any localhost/127.0.0.1 port — the dev frontend moves ports when 3000 is
    # taken, and a hardcoded list silently breaks login with a CORS error.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes are OPEN (login/setup/needs-setup); logout/me self-guard.
app.include_router(auth_router)

# Every other module now sits behind authentication. A valid session is required
# for ANY of these routes; Settings + Users additionally require an admin.
USER = [Depends(get_current_user)]
ADMIN = [Depends(require_admin)]

app.include_router(agents_router, dependencies=USER)
app.include_router(leads_router, dependencies=USER)
app.include_router(status_router, dependencies=USER)
app.include_router(supervisor_router, dependencies=USER)
app.include_router(agent1_router, dependencies=USER)
app.include_router(agent2_router, dependencies=USER)
app.include_router(agent3_router, dependencies=USER)
app.include_router(pipeline_router, dependencies=USER)
app.include_router(notifications_router, dependencies=USER)
app.include_router(it_router, dependencies=USER)
app.include_router(kb_router, dependencies=ADMIN)  # knowledge base management = admin
app.include_router(settings_router, dependencies=ADMIN)  # API keys — admin only
app.include_router(users_router)  # per-endpoint guards (admin ops + self-service)


@app.get("/health")
@safe_endpoint("app")
async def health():
    # Open, unauthenticated health check (no sensitive data).
    return {"ok": True, "storage": backend_name(), "encryption_secret_set": encryption_secret_is_set()}


# ---- intentional-failure endpoint (proves module isolation) ----------------
debug_router = APIRouter(prefix="/_debug", tags=["debug"])


@debug_router.get("/boom")
@safe_endpoint("debug")
async def boom():
    # Simulate a broken module. The safe-wrapper catches it and returns a clean
    # isolated 500; every other router keeps serving.
    raise RuntimeError("intentional failure in the debug module")


app.include_router(debug_router, dependencies=USER)
