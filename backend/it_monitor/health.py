"""Real IT Technician — health checks + deterministic status rollup + diagnosis.

Checks every dependency (Claude API, MongoDB, SMTP, IMAP) and each agent's
state, rolls them into a single 🟢/🟡/🔴 status with rule-based (NOT AI) logic,
and — only when something is wrong — asks Claude for a plain-language
explanation + fix. The whole job is safe-wrapped so it can never destabilize
the app.

Component status values: "ok" (works) | "fail" (configured but broken) |
"unconfigured" (no credentials/key set yet).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from agent3.mailer import test_imap, test_smtp
from shared.claude_client import call_claude, get_claude_key, test_connection
from shared.database import get_db
from shared.logger import get_logger
from shared.settings_store import get_setting_value

log = get_logger("it_monitor")

RISK_STUCK_MINUTES = 15          # an agent stuck in error longer than this -> risk
ERROR_SPIKE_THRESHOLD = 10       # >this many logged errors in the last hour -> spike
DEP_KEYS = ("claude_api", "mongodb", "smtp", "imap")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---- individual component checks ------------------------------------------
async def check_claude() -> dict:
    if get_claude_key() is None:
        return {"status": "unconfigured", "error": "No Claude API key set."}
    t0 = time.time()
    res = await test_connection()
    ms = int((time.time() - t0) * 1000)
    if res["ok"]:
        return {"status": "ok", "response_time_ms": ms}
    return {"status": "fail", "response_time_ms": ms, "error": res["message"]}


def check_mongo() -> dict:
    t0 = time.time()
    try:
        col = get_db()["health_ping"]
        col.update_one({"_id": "ping"}, {"$set": {"at": _iso(_now())}}, upsert=True)
        col.find_one({"_id": "ping"})
        return {"status": "ok", "response_time_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": f"DB read/write failed: {exc}"}


def check_smtp() -> dict:
    if not (get_setting_value("smtp_email") and get_setting_value("smtp_app_password")):
        return {"status": "unconfigured", "error": "SMTP credentials not set."}
    r = test_smtp()
    return {"status": "ok"} if r["ok"] else {"status": "fail", "error": r["message"]}


def check_imap() -> dict:
    if not (get_setting_value("imap_email") and get_setting_value("imap_app_password")):
        return {"status": "unconfigured", "error": "IMAP credentials not set."}
    r = test_imap()
    return {"status": "ok"} if r["ok"] else {"status": "fail", "error": r["message"]}


def check_agents() -> list[dict]:
    """Return each agent's status + how long any 'error' agent has been stuck."""
    tracking = get_db()["agent_error_since"]
    out = []
    for a in get_db()["agents"].find({}):
        entry = {"agent_id": a["id"], "name": a.get("name", a["id"]), "status": a.get("status", "offline")}
        if a.get("status") == "error":
            doc = tracking.find_one({"agent_id": a["id"]})
            if doc is None:
                tracking.insert_one({"agent_id": a["id"], "since": _iso(_now())})
                since = _now()
            else:
                since = datetime.fromisoformat(doc["since"])
            entry["stuck_since"] = _iso(since)
            entry["stuck_minutes"] = round((_now() - since).total_seconds() / 60, 1)
        else:
            tracking.delete_one({"agent_id": a["id"]})  # recovered
        out.append(entry)
    return out


def check_error_spike() -> dict:
    try:
        cutoff = (_now().timestamp() - 3600)
        recent = [e for e in get_db()["error_events"].find({}) if _ts(e.get("at", "")) >= cutoff]
        return {"count_last_hour": len(recent), "spike": len(recent) > ERROR_SPIKE_THRESHOLD}
    except Exception:  # noqa: BLE001
        return {"count_last_hour": 0, "spike": False}


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


# ---- deterministic rollup --------------------------------------------------
def rollup(components: dict) -> str:
    """Rule-based overall status. Thresholds:
    RISK  : claude_api fail | mongodb fail | any agent stuck>15min | >1 dependency 'fail'
    WARN  : smtp/imap fail | any dependency 'unconfigured' | single agent error<15min | error spike
    OK    : otherwise
    """
    deps = {k: components[k]["status"] for k in DEP_KEYS}
    fails = [k for k, v in deps.items() if v == "fail"]
    unconfigured = [k for k, v in deps.items() if v == "unconfigured"]

    agents = components.get("agents", [])
    error_agents = [a for a in agents if a["status"] in ("error", "risk")]
    stuck_long = any(a.get("stuck_minutes", 0) >= RISK_STUCK_MINUTES for a in error_agents)

    # RISK
    if deps["claude_api"] == "fail" or deps["mongodb"] == "fail" or stuck_long or len(fails) > 1:
        return "risk"
    # WARNING
    if fails or unconfigured or error_agents or components.get("error_spike", {}).get("spike"):
        return "warning"
    return "ok"
