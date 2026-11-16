"""The UI must always be able to stop waiting for a hunt.

The leads page polls /agent1/hunt-status/<run_id> every 4 seconds and leaves
its "Hunting…" state only when the answer is not "running". Two paths used to
leave it waiting forever, which is the stuck spinner the CEO kept hitting:

  1. The poll loop did `catch { continue; }` on any network error, with no
     limit. An API restart or a dropped connection meant it span forever with
     no error shown and no way back. Fixed in the frontend with a failure cap.

  2. The run store `_HUNT_RUNS` lives in memory, so an API restart loses it
     AND kills the hunt's asyncio task. hunt_status then answered ok:False,
     which the page treated as a transient blip and kept polling. It now
     answers status "gone" — a definitive end state.

This file pins the backend half. The contract that matters: for ANY run_id,
hunt_status returns a status the UI recognises as finished, or "running".
"""

from __future__ import annotations

import pathlib
import sys
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Every status the frontend treats as "stop waiting".
_TERMINAL = {"done", "error", "stopped", "gone"}


class HuntStatusContractTests(unittest.TestCase):
    def setUp(self):
        from agent1 import agent1_routes
        self.routes = agent1_routes
        self._saved = dict(agent1_routes._HUNT_RUNS)
        agent1_routes._HUNT_RUNS.clear()

    def tearDown(self):
        self.routes._HUNT_RUNS.clear()
        self.routes._HUNT_RUNS.update(self._saved)

    def test_unknown_run_id_is_terminal_not_an_error(self):
        """The case that hung: a run the server no longer knows about.

        It must NOT come back ok:False, which the page reads as a blip worth
        retrying. It must come back with a status that ends the wait.
        """
        r = self.routes.hunt_status("hunt_doesnotexist")
        self.assertTrue(r["ok"], "ok:False makes the UI keep polling forever")
        self.assertIn(r["status"], _TERMINAL)
        self.assertEqual(r["status"], "gone")

    def test_unknown_run_id_explains_itself(self):
        """The CEO sees this text, so it must say what happened."""
        msg = self.routes.hunt_status("hunt_gone").get("message", "").lower()
        self.assertTrue(msg, "a terminal status with no message tells nobody anything")
        self.assertIn("restart", msg)

    def test_unknown_run_id_does_not_claim_a_finished_hunt(self):
        """Reporting complete/found would look like a hunt that found nothing."""
        r = self.routes.hunt_status("hunt_gone")
        self.assertFalse(r.get("complete"))
        self.assertEqual(r.get("found", 0), 0)

    def test_running_hunt_is_reported_as_running(self):
        self.routes._HUNT_RUNS["hunt_live"] = {
            "id": "hunt_live", "status": "running", "message": "Round 2…"}
        r = self.routes.hunt_status("hunt_live")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "running")

    def test_every_stored_status_is_running_or_terminal(self):
        """No status may fall outside what the UI knows how to handle."""
        for status in ("running", "done", "error", "stopped"):
            with self.subTest(status=status):
                self.routes._HUNT_RUNS["h"] = {"id": "h", "status": status}
                got = self.routes.hunt_status("h")["status"]
                self.assertTrue(got == "running" or got in _TERMINAL,
                                f"UI cannot handle status {got!r}")


class FrontendPollGuardTests(unittest.TestCase):
    """The frontend half, checked in source: the retry cap must exist.

    A test cannot easily run the React component here, but the absence of a
    bound on the retry loop is the whole bug, so its presence is asserted.
    """

    def test_poll_loop_caps_consecutive_failures(self):
        src = (BACKEND_DIR.parent / "components" / "ui" / "LeadHunter.tsx").read_text(
            encoding="utf-8")
        self.assertIn("MAX_FAILURES", src,
                      "pollHunt must bound its retries or it spins forever")
        self.assertNotIn("catch { continue; }", src,
                         "an unbounded `catch { continue; }` is the stuck-spinner bug")

    def test_poll_loop_handles_gone(self):
        src = (BACKEND_DIR.parent / "components" / "ui" / "LeadHunter.tsx").read_text(
            encoding="utf-8")
        self.assertIn('"gone"', src,
                      "the page must leave its busy state when a run is gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
