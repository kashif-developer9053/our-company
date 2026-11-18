"""The database breaker: an Atlas outage must not freeze the app.

On 2026-11-16 at 11:00 UTC Atlas stopped answering for a few minutes. The app
stayed frozen for TWENTY-FOUR HOURS and needed a manual restart. The outage
belonged to Atlas; the twenty-four hours belonged to us.

The mechanism: pymongo is synchronous, so a call that never returns pins the
FastAPI event loop, and that one loop serves every request. Once pinned,
nothing else runs — not the next request, not /health, and not the code that
would have noticed Atlas had recovered.

Bounding each call with socketTimeoutMS is necessary but not sufficient: a lead
hunt makes roughly 200 database calls, so at 8s each an outage still costs ~27
minutes of frozen app, and the next hunt restarts the clock. The breaker is
what makes the cost bounded regardless of how long Atlas stays away.

These tests are the guard against someone removing it later because "pymongo
has timeouts already".
"""

from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import database as D  # noqa: E402


class DeadCollection:
    """A collection that always times out, like Atlas during the outage."""

    def __init__(self, delay: float = 0.02):
        self.calls = 0
        self.delay = delay

    def find_one(self, *a, **k):
        self.calls += 1
        time.sleep(self.delay)      # stands in for the real socket wait
        raise TimeoutError("[Errno 110] Connection timed out")


class LiveCollection:
    def find_one(self, *a, **k):
        return {"ok": True}


class BreakerTests(unittest.TestCase):

    def setUp(self):
        # The breaker is module state; every test starts from closed.
        D._breaker_failures = 0
        D._breaker_opened_at = None

    def test_breaker_opens_and_stops_calling_a_dead_mongo(self):
        """After a few timeouts we must stop asking, not keep waiting."""
        dead = DeadCollection()
        col = D._GuardedCollection(dead)

        fast_fails = real_waits = 0
        for _ in range(30):
            try:
                col.find_one({})
            except D.DatabaseUnavailable:
                fast_fails += 1
            except TimeoutError:
                real_waits += 1

        self.assertEqual(real_waits, D._BREAKER_THRESHOLD,
                         "only the calls before the breaker tripped should wait")
        self.assertEqual(dead.calls, D._BREAKER_THRESHOLD,
                         "a tripped breaker must not touch the socket at all")
        self.assertEqual(fast_fails, 30 - D._BREAKER_THRESHOLD)
        self.assertTrue(D.breaker_state()["open"])

    def test_outage_cost_is_bounded_not_proportional(self):
        """The property that actually matters.

        Unguarded, N calls against a dead Atlas cost N x socketTimeoutMS. That
        is what turned a short outage into a day: a hunt's ~200 calls at 8s is
        ~27 minutes of frozen app, every hunt, for as long as Atlas was away.
        With the breaker the cost is capped by the threshold, whatever N is.
        """
        dead = DeadCollection(delay=0.01)
        col = D._GuardedCollection(dead)
        for _ in range(200):
            try:
                col.find_one({})
            except Exception:  # noqa: BLE001
                pass
        self.assertEqual(dead.calls, D._BREAKER_THRESHOLD,
                         f"200 calls should reach the socket {D._BREAKER_THRESHOLD} "
                         f"times, not 200 — got {dead.calls}")

    def test_breaker_closes_itself_when_mongo_returns(self):
        """Recovery must need no human and no restart.

        This is the half that was missing on 2026-11-16: Atlas came back within
        minutes, but nothing noticed, so the app stayed down until someone ran
        systemctl restart the next day.
        """
        dead = D._GuardedCollection(DeadCollection())
        for _ in range(D._BREAKER_THRESHOLD):
            try:
                dead.find_one({})
            except Exception:  # noqa: BLE001
                pass
        self.assertTrue(D.breaker_state()["open"], "precondition: breaker open")

        # Pretend the retry window has passed and Mongo is healthy again.
        D._breaker_opened_at = time.monotonic() - D._BREAKER_RETRY_AFTER - 1
        result = D._GuardedCollection(LiveCollection()).find_one({})

        self.assertEqual(result, {"ok": True})
        self.assertFalse(D.breaker_state()["open"], "a good probe must close it")
        self.assertEqual(D.breaker_state()["failures"], 0)

    def test_only_one_probe_is_let_through_per_window(self):
        """A probe must not become a flood.

        If every call during the open window were allowed to probe, the breaker
        would be decorative: each one would wait the full socket timeout again.
        """
        dead = DeadCollection()
        col = D._GuardedCollection(dead)
        for _ in range(D._BREAKER_THRESHOLD):
            try:
                col.find_one({})
            except Exception:  # noqa: BLE001
                pass
        before = dead.calls

        D._breaker_opened_at = time.monotonic() - D._BREAKER_RETRY_AFTER - 1
        for _ in range(10):
            try:
                col.find_one({})
            except Exception:  # noqa: BLE001
                pass

        self.assertEqual(dead.calls, before + 1,
                         "exactly one probe per window, not ten")

    def test_a_real_error_does_not_trip_the_breaker(self):
        """A duplicate key means Mongo answered us perfectly well.

        Tripping on application errors would take the database "down" over a
        bug in our own write path, which is the opposite of the intent.
        """
        class DupCollection:
            def insert_one(self, *a, **k):
                raise Exception("E11000 duplicate key error")

        col = D._GuardedCollection(DupCollection())
        for _ in range(D._BREAKER_THRESHOLD * 3):
            try:
                col.insert_one({})
            except Exception:  # noqa: BLE001
                pass

        self.assertFalse(D.breaker_state()["open"],
                         "application errors must never open the breaker")
        self.assertEqual(D.breaker_state()["failures"], 0)

    def test_a_success_resets_the_failure_count(self):
        """Two timeouts an hour apart are not an outage.

        Without this, isolated blips would accumulate over days and trip the
        breaker during a perfectly healthy spell.
        """
        dead = D._GuardedCollection(DeadCollection())
        live = D._GuardedCollection(LiveCollection())
        for _ in range(D._BREAKER_THRESHOLD - 1):
            try:
                dead.find_one({})
            except Exception:  # noqa: BLE001
                pass
        self.assertEqual(D.breaker_state()["failures"], D._BREAKER_THRESHOLD - 1)

        live.find_one({})
        self.assertEqual(D.breaker_state()["failures"], 0,
                         "a success must clear the streak")
        self.assertFalse(D.breaker_state()["open"])

    def test_cursor_chaining_survives_the_guard(self):
        """find(q).sort(...).limit(n) must keep working.

        This is the bug this guard nearly shipped WITH. The first version
        resolved every cursor to a list so iteration timeouts would be seen —
        but a list has no .sort(), and this codebase chains on cursors in nine
        places including the leads list (crm/leads_routes.py:195) and
        notifications (shared/notifications.py:105). It would have broken the
        leads page on deploy, and the unit tests would not have caught it
        because mongomock skips the guard entirely.
        """
        class FakeCursor:
            def __init__(self, docs):
                self.docs = list(docs)

            def sort(self, *a, **k):
                return FakeCursor(sorted(self.docs, key=lambda d: d["n"], reverse=True))

            def limit(self, n):
                return FakeCursor(self.docs[:n])

            def skip(self, n):
                return FakeCursor(self.docs[n:])

            def __iter__(self):
                return iter(self.docs)

        original = D._is_cursor
        D._is_cursor = lambda o: isinstance(o, FakeCursor)
        try:
            docs = [{"n": i} for i in range(10)]
            chained = D._GuardedCursor(FakeCursor(docs)).sort("created_at", -1).limit(3)
            self.assertEqual([d["n"] for d in chained], [9, 8, 7],
                             "sort().limit() must chain, not raise AttributeError")
            self.assertEqual(
                len(list(D._GuardedCursor(FakeCursor(docs)).limit(2))), 2)
            # Building a chain touches no network, so it must not move the breaker.
            D._breaker_failures = 0
            D._breaker_opened_at = None
            D._GuardedCursor(FakeCursor(docs)).sort("a", 1).limit(5).skip(1)
            self.assertEqual(D.breaker_state()["failures"], 0,
                             "query building must not consume breaker budget")
        finally:
            D._is_cursor = original

    def test_a_timeout_during_iteration_trips_the_breaker(self):
        """find() is lazy, so the timeout lands later — it must still count.

        The server is not contacted by find() itself; the query runs on first
        iteration. A guard that only watched the find() call would therefore
        miss the most common failure shape in this app.
        """
        class DeadCursor:
            def __iter__(self):
                raise TimeoutError("[Errno 110] died mid-iteration")

        original = D._is_cursor
        D._is_cursor = lambda o: isinstance(o, DeadCursor)
        try:
            for _ in range(D._BREAKER_THRESHOLD):
                try:
                    list(D._GuardedCursor(DeadCursor()))
                except Exception:  # noqa: BLE001
                    pass
            self.assertTrue(D.breaker_state()["open"],
                            "iteration timeouts must reach the breaker")
        finally:
            D._is_cursor = original

    def test_timeout_classification(self):
        """Only connectivity faults count as timeouts."""
        self.assertTrue(D._is_timeout(TimeoutError("110")))
        self.assertTrue(D._is_timeout(OSError("unreachable")))
        self.assertFalse(D._is_timeout(ValueError("bad input")))
        self.assertFalse(D._is_timeout(KeyError("missing")))

    def test_socket_timeout_stays_bounded(self):
        """The config must not drift back to a value that freezes the app.

        socketTimeoutMS was 20000 during the outage, and with retryReads that
        is ~40s of frozen app per call. Anything above 10s here means a single
        stalled call is long enough for a user to conclude the app is dead.
        """
        import re
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "shared", "database.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        # Anchored to the start of its own line so the postmortem comment above
        # it (which quotes the old 20000) is not what gets measured.
        m = re.search(r"^\s*socketTimeoutMS=(\d+)", src, re.MULTILINE)
        self.assertIsNotNone(m, "socketTimeoutMS must be set explicitly")
        self.assertLessEqual(int(m.group(1)), 10000,
                             "socketTimeoutMS above 10s re-creates the 2026-11-16 freeze")

    def test_min_pool_size_is_zero(self):
        """minPoolSize=5 owned the thread that raised the 11:00 NetworkTimeout.

        Warm sockets save ~200ms after an idle spell. They are not worth a
        background thread whose job is to keep reconnecting to an Atlas that
        is not answering — during precisely the outage we need to ride out.
        """
        import re
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "shared", "database.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        m = re.search(r"^\s*minPoolSize=(\d+)", src, re.MULTILINE)
        self.assertIsNotNone(m, "minPoolSize must be set explicitly")
        self.assertEqual(int(m.group(1)), 0,
                         "minPoolSize must stay 0 — see the 2026-11-16 postmortem")


if __name__ == "__main__":
    unittest.main(verbosity=2)
