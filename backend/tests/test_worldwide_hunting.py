"""Hunting outside the home market must work, and must not lie when it fails.

On 2026-11-18 a hunt for clinics in Memphis ran six rounds, found nothing, and
concluded: "this niche/area looks exhausted. Try widening the location or a
different niche."

Memphis is full of clinics. What actually happened is in the log:

    Round 4: web crawl took too long - moving on.
    Round 5: Maps took too long - moving on.
    Round 6: Maps took too long - moving on.

EVERY source timed out. Nothing was searched. Tested directly from the server
the same day, a Memphis query timed out at 75s while a Lahore query returned
five leads in 39s — so the scraper was not wedged, the distant round trip is
simply slower and 39s working left no headroom.

Two faults, and the second is the worse one:

  1. the timeout was tuned for the home market, so distant hunts failed on the
     clock;
  2. "no results" and "never got an answer" were reported identically, so the
     app stated a false conclusion about a real market with total confidence.

A wasted five minutes is cheap. Believing there is no business in Memphis is
not.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1 import lead_harvester as H  # noqa: E402


class DistanceAwareTimeoutTests(unittest.TestCase):

    def test_home_market_keeps_the_short_timeout(self):
        """Pakistani hunts were working; they must not get slower to debug."""
        for where in ["Lahore, Pakistan", "Islamabad, Pakistan",
                      "Karachi, pakistan", "Murree, PAKISTAN"]:
            with self.subTest(where=where):
                self.assertEqual(H._timeout_for(where), H._SOURCE_TIMEOUT)

    def test_distant_searches_get_longer(self):
        """The Memphis case, plus the other places the CEO might hunt."""
        for where in ["Memphis, United states", "London, United Kingdom",
                      "Dubai, UAE", "Toronto, Canada"]:
            with self.subTest(where=where):
                self.assertEqual(H._timeout_for(where), H._SOURCE_TIMEOUT_FAR)

    def test_far_timeout_clears_the_measured_working_time(self):
        """A Lahore search took 39s WORKING, from the same server.

        Whatever the far ceiling is, it has to be comfortably above a
        measured-good time, or distant hunts fail on the clock again.
        """
        self.assertGreaterEqual(
            H._SOURCE_TIMEOUT_FAR, 120,
            "a measured-good query took 39s; the far ceiling needs real headroom")

    def test_an_unknown_location_is_treated_as_distant(self):
        """Being too patient costs seconds. Being too impatient costs the hunt."""
        for where in ["", "Somewhere", "Mars"]:
            with self.subTest(where=where):
                self.assertEqual(H._timeout_for(where), H._SOURCE_TIMEOUT_FAR)


class HonestFailureTests(unittest.TestCase):
    """The app must not report a connection problem as a market verdict."""

    def _source(self) -> str:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", "lead_harvester.py")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_timeout_rounds_are_counted_separately_from_barren_rounds(self):
        """"Found nothing" and "never answered" must not share a counter."""
        src = self._source()
        self.assertIn("timeout_rounds", src,
                      "rounds where every source timed out need their own count")
        self.assertIn("any_source_answered", src,
                      "each round must record whether anything actually answered")

    def test_every_source_sets_the_answered_flag(self):
        """A source that answers must say so, or the count is wrong.

        If one source forgets, a round where only that source worked still
        looks like a total timeout, and the hunt stops early blaming the
        connection for a market that answered.
        """
        src = self._source()
        # Each source awaits with the shared timeout; each must mark success.
        awaits = len(re.findall(r"timeout=_src_timeout\)", src))
        marks = len(re.findall(r"any_source_answered = True", src))
        self.assertGreaterEqual(
            marks, 3,
            f"found {awaits} timed sources but only {marks} set the answered flag")

    def test_the_timeout_message_does_not_blame_the_market(self):
        """The exact sentence that misled the CEO must not be reachable.

        The timeout branch must say the search failed on our side, and must
        NOT suggest the area is empty or that a different niche would help.
        """
        src = self._source()
        m = re.search(r'say\(f"Every search source timed out[^)]*\)', src, re.S)
        self.assertIsNotNone(m, "a timeout-specific message must exist")
        message = m.group(0)
        self.assertIn("NOT an empty market", message,
                      "the message must correct the wrong conclusion explicitly")
        self.assertNotIn("exhausted", message,
                         "a timeout must never be described as an exhausted area")

    def test_the_hunt_stops_quickly_when_nothing_answers(self):
        """Six dead rounds taught us nothing. Two is enough to see the pattern."""
        self.assertLessEqual(
            H._TIMEOUT_ROUNDS_LIMIT, 3,
            "burning more than ~3 rounds on sources that never answer is waste")
        self.assertGreaterEqual(
            H._TIMEOUT_ROUNDS_LIMIT, 2,
            "one timeout is a blip, not a pattern — do not quit on the first")

    def test_the_timeout_check_runs_before_the_exhausted_check(self):
        """Order matters: whichever fires first decides what the CEO is told.

        Both conditions are true during a total-timeout hunt, so if the
        exhausted branch is reached first the false message is printed anyway
        and this whole fix is inert.
        """
        src = self._source()
        # Match the say() calls themselves, not the comments above them that
        # quote the same words while explaining the bug.
        timeout_at = src.find('say(f"Every search source timed out')
        exhausted_at = src.find('this niche/area looks exhausted. "')
        self.assertNotEqual(timeout_at, -1)
        self.assertNotEqual(exhausted_at, -1)
        self.assertLess(timeout_at, exhausted_at,
                        "the timeout branch must be checked first, or it never fires")


class ScraperSpeedTests(unittest.TestCase):
    """The scraper was slow enough that distance alone broke it."""

    def _source(self) -> str:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", "scraper.py")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_heavy_resources_are_blocked(self):
        """Maps is a map: tiles and photos are most of the bytes.

        This scraper reads four strings per business. Downloading the imagery
        is pure cost, and it is the cost that pushed a distant query past the
        timeout.
        """
        src = self._source()
        # Must be a LIVE call, not a commented-out one: an earlier version of
        # this test passed happily against `# await context.route(...)`, which
        # is exactly the regression it exists to catch.
        self.assertRegex(
            src, r'(?m)^\s*await context\.route\(',
            "resource blocking must be installed and not commented out")
        for kind in ("image", "media", "font"):
            with self.subTest(kind=kind):
                self.assertIn(f'"{kind}"', src, f"{kind} requests should be aborted")

    def test_detail_pages_are_read_in_parallel(self):
        """20 businesses meant 20 sequential page loads — most of the 39s.

        They are independent URLs, so the only thing being paid for was round
        trip latency, one at a time.
        """
        src = self._source()
        self.assertIn("_DETAIL_CONCURRENCY", src)
        self.assertIn("asyncio.gather", src,
                      "detail pages must be fetched concurrently")
        self.assertGreaterEqual(
            __import__("agent1.scraper", fromlist=["x"])._DETAIL_CONCURRENCY, 2,
            "concurrency below 2 is sequential with extra steps")

    def test_tabs_are_closed(self):
        """A leaked tab is a leaked renderer process.

        A hunt runs dozens of rounds; leaking a tab per business is how the
        server's memory walks up until nothing can be served.
        """
        src = self._source()
        self.assertIn("tab.close()", src, "each detail tab must be closed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
