"""IT Technician — generate, isolate-test, and (on CEO approval) deploy new agents.

SAFETY MODEL (the whole point of this phase):
- Generated code is written to an ISOLATED staging dir, never the live package.
- It is tested in a SEPARATE Python SUBPROCESS with a timeout and an in-memory
  DB — so a broken/misbehaving generated module can never affect the running app.
- Nothing is imported into the live process automatically. On approval the agent
  goes LIVE via the existing dynamic agent system (a DB record → it renders on the
  map + gets a real chat endpoint), and the generated module file is saved to the
  repo (backend/generated_agents/) as a starting point for a developer to extend.
  We intentionally do NOT hot-import arbitrary generated Python into the live
  process — that would break the isolation guarantee.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone

from shared.claude_client import call_claude, get_claude_key
from shared.database import get_db
from shared.logger import get_logger

log = get_logger("agent_builder")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_ROOT = os.path.join(BACKEND_DIR, ".build_staging")
GENERATED_DIR = os.path.join(BACKEND_DIR, "generated_agents")

CODEGEN_SYSTEM = (
    "You generate a single Python module for a new agent in an existing FastAPI codebase. "
    "The module MUST define exactly: a string SYSTEM (the agent's role/system prompt), "
    "a function run_core(sample: dict) -> dict (its core logic, wrapped in try/except, returning "
    "a dict; stub any real external integration and never call the network), and an async function "
    "chat(message: str, history: list) -> dict that calls `from shared.claude_client import call_claude` "
    "and returns {'ok': bool, 'reply'|'error': ...}. Follow safe try/except isolation. Output ONLY the "
    "Python code, no markdown fences, no prose."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or f"agent_{uuid.uuid4().hex[:6]}"


def _template_module(name: str, description: str) -> str:
    """A safe, valid fallback module (used when Claude is unavailable, or if the
    Claude output fails its isolated tests)."""
    safe_desc = description.replace('"""', "'''")
    return f'''"""Generated agent: {name}. Built by the IT Technician (template)."""
from __future__ import annotations

from shared.claude_client import call_claude
from shared.logger import get_logger

log = get_logger("generated.{_slug(name)}")

SYSTEM = (
    "You are {name}, a member of a small digital agency's automated team. "
    "Your responsibility: {safe_desc}. "
    "Answer grounded in real data. If asked to perform a capability that has not been "
    "built yet for this agent, say so honestly. Be concise."
)


def run_core(sample: dict) -> dict:
    """Core logic. Real external integration is intentionally stubbed until wired up."""
    try:
        return {{"ok": True, "note": "stub core executed (no real integration yet)", "input": sample}}
    except Exception as exc:  # safe-wrapper isolation
        log.error("run_core failed: %s", exc)
        return {{"ok": False, "error": str(exc)}}


async def chat(message: str, history: list | None = None) -> dict:
    messages = []
    for m in (history or [])[-8:]:
        messages.append({{"role": "assistant" if m.get("role") == "agent" else "user",
                          "content": str(m.get("content", ""))}})
    messages.append({{"role": "user", "content": message}})
    res = await call_claude(SYSTEM, messages, max_tokens=400)
    if res["ok"]:
        return {{"ok": True, "reply": res["text"]}}
    return {{"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}}
'''


_TEST_RUNNER = r'''
import sys, json, importlib.util, asyncio
mod_path = sys.argv[1]
results = []
spec = importlib.util.spec_from_file_location("generated_agent_under_test", mod_path)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    results.append({"check_name": "module_imports", "passed": True, "detail": "imported cleanly"})
except Exception as e:
    results.append({"check_name": "module_imports", "passed": False, "detail": f"{type(e).__name__}: {e}"})
    print(json.dumps(results)); sys.exit(0)
try:
    r = mod.run_core({"sample": "test"})
    results.append({"check_name": "core_dummy_run", "passed": isinstance(r, dict), "detail": str(r)[:140]})
except Exception as e:
    results.append({"check_name": "core_dummy_run", "passed": False, "detail": f"{type(e).__name__}: {e}"})
try:
    r = asyncio.run(mod.chat("hello, this is a test", []))
    ok = isinstance(r, dict) and "ok" in r
    results.append({"check_name": "chat_responds", "passed": ok, "detail": str(r)[:140]})
except Exception as e:
    results.append({"check_name": "chat_responds", "passed": False, "detail": f"{type(e).__name__}: {e}"})
print(json.dumps(results))
'''


async def _generate_code(name: str, description: str, needs_reasoning: bool, feedback: str = "") -> tuple[str, list[str]]:
    """Return (code, warnings). Uses Claude if a key is set; else a safe template."""
    warnings: list[str] = []
    if get_claude_key() is None:
        warnings.append("No Claude API key set — used a safe deterministic template instead of Claude code generation.")
        return _template_module(name, description), warnings
    prompt = (
        f"New agent name: {name}\nWhat it should do: {description}\n"
        f"Needs Claude reasoning: {needs_reasoning}\n"
        + (f"Reviewer feedback to address: {feedback}\n" if feedback else "")
        + "Generate the module now."
    )
    res = await call_claude(CODEGEN_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=1500)
    if not res["ok"]:
        warnings.append(f"Claude code generation failed ({res['error']}); used a safe template instead.")
        return _template_module(name, description), warnings
    code = res["text"].strip()
    # Strip accidental markdown fences.
    fence = re.search(r"```(?:python)?\s*(.+?)```", code, re.DOTALL)
    if fence:
        code = fence.group(1).strip()
    if "def run_core" not in code or "async def chat" not in code or "SYSTEM" not in code:
        warnings.append("Claude output didn't follow the required interface; used a safe template instead.")
        return _template_module(name, description), warnings
    return code, warnings


async def _run_isolated_tests(module_path: str) -> list[dict]:
    """Import + exercise the generated module in a SEPARATE process (isolated)."""
    runner_path = os.path.join(os.path.dirname(module_path), "_test_runner.py")
    with open(runner_path, "w", encoding="utf-8") as f:
        f.write(_TEST_RUNNER)
    env = dict(os.environ)
    env["MONGO_URI"] = ""  # force in-memory DB in the test process
    env["PYTHONPATH"] = BACKEND_DIR + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, runner_path, module_path,
            cwd=BACKEND_DIR, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=40)
        text = out.decode(errors="replace").strip()
        line = text.splitlines()[-1] if text else ""
        return json.loads(line)
    except asyncio.TimeoutError:
        return [{"check_name": "isolated_run", "passed": False, "detail": "Test process timed out (40s) — killed. No effect on live app."}]
    except Exception as exc:  # noqa: BLE001
        return [{"check_name": "isolated_run", "passed": False, "detail": f"Test harness error: {exc}"}]


def _set_it(status: str, task: str) -> None:
    get_db()["agents"].update_one({"id": "it_monitor"}, {"$set": {"status": status, "task": task}})


async def build_agent(request_id: str, name: str, description: str, needs_reasoning: bool, feedback: str = "") -> None:
    """Full background build: generate -> stage -> isolated test -> (self-correct) -> report."""
    reqs = get_db()["agent_build_requests"]
    try:
        _set_it("working", f"Building new agent: {name}")
        os.makedirs(STAGING_ROOT, exist_ok=True)
        stage_dir = os.path.join(STAGING_ROOT, request_id)
        if os.path.isdir(stage_dir):
            shutil.rmtree(stage_dir, ignore_errors=True)
        os.makedirs(stage_dir, exist_ok=True)
        slug = _slug(name)
        module_path = os.path.join(stage_dir, f"{slug}.py")

        code, warnings = await _generate_code(name, description, needs_reasoning, feedback)
        with open(module_path, "w", encoding="utf-8") as f:
            f.write(code)

        results = await _run_isolated_tests(module_path)

        # One round of self-correction on failure.
        if not all(r["passed"] for r in results):
            fail_detail = "; ".join(f"{r['check_name']}: {r['detail']}" for r in results if not r["passed"])
            code, w2 = await _generate_code(name, description, needs_reasoning, feedback=f"Previous attempt failed these checks: {fail_detail}. Fix them.")
            warnings += w2
            warnings.append("Self-correction round performed after initial test failure.")
            with open(module_path, "w", encoding="utf-8") as f:
                f.write(code)
            results = await _run_isolated_tests(module_path)

        overall_ready = all(r["passed"] for r in results)
        if "stub core executed" in code or "template" in code.lower():
            warnings.append("This agent's core logic is a safe stub — real integration must be wired up before it does actual work.")

        reqs.update_one({"request_id": request_id}, {"$set": {
            "status": "awaiting_review",
            "agent_name": name, "description_given": description,
            "files_added": [f"generated_agents/{slug}.py (on approval)"],
            "files_modified": [],
            "staged_module": module_path, "slug": slug,
            "test_results": results, "warnings": warnings,
            "overall_ready": overall_ready, "generated_at": _now(),
        }})
        _set_it("idle", "")
        log.info("Agent build report ready for '%s' (ready=%s)", name, overall_ready)
    except Exception as exc:  # noqa: BLE001 - the builder itself must never crash the app
        log.error("Agent build crashed (isolated): %s", exc)
        _set_it("idle", "")
        reqs.update_one({"request_id": request_id}, {"$set": {
            "status": "awaiting_review", "overall_ready": False,
            "warnings": [f"Build process error: {exc}"], "test_results": [], "generated_at": _now(),
        }})


def deploy_agent(request_id: str) -> dict:
    """On CEO approval: save the generated file to the repo + register the agent
    live via the dynamic system. Returns the created agent."""
    from agents.agent_registry import _col as agents_col  # local import avoids cycle

    reqs = get_db()["agent_build_requests"]
    req = reqs.find_one({"request_id": request_id})
    if req is None:
        raise ValueError("Request not found")
    slug = req.get("slug") or _slug(req.get("agent_name", "agent"))
    staged = req.get("staged_module")

    # Save the generated module into the repo (developer starting point).
    os.makedirs(GENERATED_DIR, exist_ok=True)
    init_path = os.path.join(GENERATED_DIR, "__init__.py")
    if not os.path.exists(init_path):
        open(init_path, "w").close()
    dest = os.path.join(GENERATED_DIR, f"{slug}.py")
    if staged and os.path.exists(staged):
        shutil.copyfile(staged, dest)

    # Register live via the dynamic agent system (renders on map + generic chat).
    board = get_db()["status_board"].find_one({"_id": "singleton"})
    initial = "idle" if (board and board.get("office_open")) else "offline"
    agent = {
        "id": f"custom_{uuid.uuid4().hex[:8]}",
        "name": req["agent_name"], "role_key": "custom",
        "responsibility": req.get("description_given", ""),
        "status": initial, "location": "employee_room", "is_default": False,
        "created_at": _now(), "task": "",
    }
    agents_col().insert_one(dict(agent))

    reqs.update_one({"request_id": request_id}, {"$set": {"status": "approved", "deployed_file": f"generated_agents/{slug}.py", "live_agent_id": agent["id"]}})
    # Clean up staging.
    stage_dir = os.path.join(STAGING_ROOT, request_id)
    shutil.rmtree(stage_dir, ignore_errors=True)
    return {k: agent[k] for k in ("id", "name", "role_key", "responsibility", "status", "is_default")}


def reject_request(request_id: str, feedback: str = "") -> None:
    """Discard the isolated code entirely; nothing touches the live app."""
    reqs = get_db()["agent_build_requests"]
    reqs.update_one({"request_id": request_id}, {"$set": {"status": "rejected", "feedback": feedback}})
    shutil.rmtree(os.path.join(STAGING_ROOT, request_id), ignore_errors=True)
