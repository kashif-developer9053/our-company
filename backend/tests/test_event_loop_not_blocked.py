"""Route handlers must not block the event loop.

Every route here talks to MongoDB through pymongo, which is SYNCHRONOUS. How a
handler is declared therefore decides where that blocking I/O runs:

    async def  ->  on the event loop   : stalls EVERY other request
    def        ->  in the threadpool   : only that request waits

Declaring a blocking handler `async def` is what made the app "stick on
loading" and return 504 on login: one slow Atlas query, or a running lead
hunt, held the loop and nginx gave up waiting. It is an easy mistake to
reintroduce, because `async def` looks more modern and the code still works
under light load, so it is asserted here.

The rule: a route handler may be `async def` ONLY if it actually awaits
something. If it awaits nothing, it is doing blocking work and must be `def`.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import sys
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Mongo calls that block until the server answers.
_BLOCKING_DB_CALLS = {
    "find_one", "find", "insert_one", "insert_many", "update_one",
    "update_many", "delete_one", "delete_many", "count_documents",
    "aggregate", "bulk_write", "replace_one", "find_one_and_update",
}


def _route_handlers():
    """Every @router-decorated handler in the backend, with its AST node."""
    for path in sorted(BACKEND_DIR.rglob("*_routes.py")):
        if "backend-venv" in str(path) or "/tests/" in str(path).replace("\\", "/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(ast.unparse(d).startswith("router.")
                       for d in node.decorator_list):
                continue
            yield path, node


def _needs_event_loop(node: ast.AST) -> bool:
    """Does this handler have a real reason to be `async def`?

    Awaiting something is the obvious one. `asyncio.create_task(...)` is the
    other: it schedules background work and requires a running loop, so those
    handlers must stay async even though they await nothing themselves.
    """
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            return True
        if isinstance(sub, ast.Call):
            call = ast.unparse(sub.func)
            if call.endswith(("create_task", "ensure_future", "get_running_loop")):
                return True
    return False


def _blocking_db_calls(node: ast.AST) -> int:
    n = 0
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in _BLOCKING_DB_CALLS):
            n += 1
    return n


class HandlerDeclarationTests(unittest.TestCase):
    def test_async_handlers_have_a_reason_to_be_async(self):
        """An `async def` with no await and no create_task blocks the loop."""
        offenders = [
            f"{p.name}:{n.name}"
            for p, n in _route_handlers()
            if isinstance(n, ast.AsyncFunctionDef) and not _needs_event_loop(n)
        ]
        self.assertEqual(
            offenders, [],
            "These handlers are `async def` but await nothing, so their "
            "blocking pymongo calls run on the event loop and stall every "
            "other request (this is the 504-on-login bug). Declare them "
            "`def` — FastAPI will run them in its threadpool:\n  "
            + "\n  ".join(offenders))

    def test_there_are_sync_handlers(self):
        """Guard against the AST walk silently finding nothing."""
        kinds = [type(n).__name__ for _, n in _route_handlers()]
        self.assertGreater(kinds.count("FunctionDef"), 50,
                           "expected most handlers to be plain `def`")


class SafeEndpointTests(unittest.TestCase):
    """safe_endpoint must not turn a sync handler into an async one.

    It used to always return an `async` wrapper, which silently undid any
    `def` declaration: FastAPI inspects the WRAPPER, so the handler ran on
    the loop regardless of how it was written.
    """

    def setUp(self):
        from shared.safe_wrapper import safe_endpoint
        self.safe_endpoint = safe_endpoint

    def test_sync_handler_stays_sync(self):
        @self.safe_endpoint("test")
        def handler():
            return {"ok": True}

        self.assertFalse(inspect.iscoroutinefunction(handler))
        self.assertEqual(handler(), {"ok": True})

    def test_async_handler_stays_async(self):
        import asyncio

        @self.safe_endpoint("test")
        async def handler():
            return {"ok": True}

        self.assertTrue(inspect.iscoroutinefunction(handler))
        self.assertEqual(asyncio.run(handler()), {"ok": True})

    def test_http_exception_still_passes_through(self):
        from fastapi import HTTPException

        @self.safe_endpoint("test")
        def handler():
            raise HTTPException(status_code=401, detail="nope")

        with self.assertRaises(HTTPException) as ctx:
            handler()
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unexpected_error_is_isolated_as_500(self):
        @self.safe_endpoint("test")
        def handler():
            raise ValueError("boom")

        self.assertEqual(handler().status_code, 500)


class AuthHandlerTests(unittest.TestCase):
    """Login is the route that must never be blocked — it is how you get in."""

    def test_login_is_not_async(self):
        from auth import auth_routes
        for name in ("login", "setup", "needs_setup", "me", "logout"):
            with self.subTest(handler=name):
                fn = getattr(auth_routes, name)
                self.assertFalse(
                    inspect.iscoroutinefunction(fn),
                    f"auth.{name} must be `def`: it does blocking pymongo "
                    f"work (login also runs bcrypt) and an async declaration "
                    f"puts that on the event loop.")


class RemainingBlockingCallsTests(unittest.TestCase):
    def test_blocking_calls_in_async_handlers_do_not_grow(self):
        """A ratchet, not a clean bill of health.

        These async handlers legitimately await (AI calls, email, hunts) but
        still make some synchronous Mongo calls inline. Each one briefly holds
        the loop. The count is capped so the problem shrinks rather than
        creeps back; lower the cap as they are moved to asyncio.to_thread.
        """
        total = sum(_blocking_db_calls(n) for _, n in _route_handlers()
                    if isinstance(n, ast.AsyncFunctionDef))
        self.assertLessEqual(
            total, 26,
            "More blocking Mongo calls were added inside async handlers. "
            "Wrap them in `await asyncio.to_thread(...)` instead.")


class BackgroundLoopTests(unittest.TestCase):
    """The long-running loops in app_entry must not block the event loop.

    These were missed by the first pass, which only looked at route handlers.
    Five loops run forever from lifespan, waking every 2-10 minutes; four of
    them made synchronous pymongo calls directly on the loop. That froze every
    request in the process for as long as Atlas took to answer, with no hunt
    running and nobody logged in - so the app "stuck on loading" on its own.

    The worst two: _health_check_loop ran list(find({})) over every strategic
    review every 3 minutes, and _followup_loop scanned the whole leads
    collection via due_leads().
    """

    LOOPS = ("_prune_loop", "_health_check_loop", "_queued_send_loop",
             "_followup_loop", "_reply_check_loop")

    def _loop_nodes(self):
        tree = ast.parse((BACKEND_DIR / "app_entry.py").read_text(encoding="utf-8"))
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in self.LOOPS:
                found[node.name] = node
        return found

    def test_all_loops_were_found(self):
        """Guard against the loops being renamed and the check going quiet."""
        self.assertEqual(set(self._loop_nodes()), set(self.LOOPS))

    def test_no_loop_calls_mongo_on_the_event_loop(self):
        """Every blocking DB call in a loop must be inside asyncio.to_thread."""
        offenders = []
        for name, node in self._loop_nodes().items():
            for sub in ast.walk(node):
                if not (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in _BLOCKING_DB_CALLS):
                    continue
                # Walk up: a call wrapped in to_thread(...) is fine. The AST
                # gives no parent pointers, so test the enclosing source.
                src = ast.unparse(node)
                if "to_thread" not in src:
                    offenders.append(f"{name}:{sub.func.attr}")
        self.assertEqual(
            offenders, [],
            "These background loops make blocking Mongo calls with no "
            "asyncio.to_thread anywhere in the function, so they stall every "
            "request while the query runs:\n  " + "\n  ".join(offenders))

    def test_each_blocking_loop_uses_to_thread(self):
        """Per-loop, so a regression names the loop that broke."""
        for name, node in self._loop_nodes().items():
            src = ast.unparse(node)
            has_db = any(
                isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in _BLOCKING_DB_CALLS
                for sub in ast.walk(node))
            if not has_db:
                continue
            with self.subTest(loop=name):
                self.assertIn(
                    "to_thread", src,
                    f"{name} does blocking DB work on the event loop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
