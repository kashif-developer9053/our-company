"""Every timeout must be shorter than the one that contains it.

Four limits govern one Maps scrape, and they were set at four different times
by four different pieces of reasoning:

    scraper   page.goto                  45s
    scraper   feed.wait_for              12s
    harvester one source, home market    75s
    harvester whole round               150s

Measured on the VPS, 2026-11-21, six consecutive runs of the same query:

    navigation:      2s, 4s, 29s, 31s, 48s, 58s
    to a drawn feed: 59s, 61s, 69s

Every run delivered businesses and none logged an HTTP error. The page is
just slow from that machine - about ten times slower than from the developer
machine where all four numbers were chosen - so a working scrape was being
cut off and reported as "No results feed found (0 businesses)". The harvester
passed that on as an exhausted market, and the CEO was told Seattle has no
landscapers.

The subtler fault is the ORDERING. An inner limit above its outer one is
always a bug, whatever the numbers: the inner work is permitted time it can
never actually use, and it is cut off precisely in the runs that were about
to succeed, because slow runs are the ones that reach the limit. Raising
_SOURCE_TIMEOUT_FAR to 160 while _ROUND_TIMEOUT sat at 150 created exactly
that - one rule allowing 160s, another killing it at 150s.

So these tests assert the relationships, not the values. Tuning a number for
a faster machine stays allowed; inverting the nesting does not.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1 import lead_harvester as H  # noqa: E402
from agent1 import scraper as S  # noqa: E402


# The slowest SUCCESSFUL scrape observed on the VPS. Any ceiling at or below
# this would cut off a scrape that was working.
#
# First recorded as 69s, from runs where the layout bug was still making some
# attempts fail fast. Once the scrape worked end to end, four consecutive runs
# returning five leads each measured 115s, 118s, 121s and 126s - so three of
# the four exceeded the 120s ceiling that was in place at the time, and the
# limit meant to catch a wedged source was discarding ordinary ones.
_SLOWEST_OBSERVED_SUCCESS = 126


class TimeoutsNestTests(unittest.TestCase):

    def test_a_round_outlasts_the_slowest_source_it_runs(self):
        """_ROUND_TIMEOUT 150 vs _SOURCE_TIMEOUT_FAR 160 was the inversion."""
        self.assertGreater(
            H._ROUND_TIMEOUT, H._SOURCE_TIMEOUT_FAR,
            f"a round is capped at {H._ROUND_TIMEOUT}s but one source inside "
            f"it may take {H._SOURCE_TIMEOUT_FAR}s - the round will kill a "
            f"source that is still within its own allowance")

    def test_a_round_outlasts_the_home_market_source_too(self):
        self.assertGreater(H._ROUND_TIMEOUT, H._SOURCE_TIMEOUT)

    def test_a_source_outlasts_the_page_load_it_waits_on(self):
        """The scrape's own ceiling must fit inside the harvester's."""
        goto_s = S._GOTO_TIMEOUT_MS / 1000
        self.assertGreaterEqual(
            H._SOURCE_TIMEOUT, goto_s,
            f"a source is abandoned at {H._SOURCE_TIMEOUT}s but the scraper "
            f"is still allowed {goto_s}s just to load the page")
        self.assertGreaterEqual(H._SOURCE_TIMEOUT_FAR, goto_s)

    def test_the_far_ceiling_is_not_below_the_home_one(self):
        """Distance costs time; the far case must never be the stricter one."""
        self.assertGreaterEqual(H._SOURCE_TIMEOUT_FAR, H._SOURCE_TIMEOUT)

    def test_every_ceiling_clears_the_slowest_measured_success(self):
        """The whole outage in one assertion.

        Each of these was below 69s at some point, and each one turned a
        working scrape into "this market is empty".
        """
        for name, seconds in (
            ("scraper page.goto", S._GOTO_TIMEOUT_MS / 1000),
            ("harvester source (home)", H._SOURCE_TIMEOUT),
            ("harvester source (far)", H._SOURCE_TIMEOUT_FAR),
            ("harvester round", H._ROUND_TIMEOUT),
        ):
            with self.subTest(limit=name):
                self.assertGreater(
                    seconds, _SLOWEST_OBSERVED_SUCCESS,
                    f"{name} is {seconds}s, but a SUCCESSFUL scrape was "
                    f"measured at {_SLOWEST_OBSERVED_SUCCESS}s on the "
                    f"production server - this ceiling discards working runs")

    def test_the_feed_wait_leaves_room_after_a_slow_navigation(self):
        """goto and feed.wait_for are sequential, inside one source budget.

        The feed wait starts only after navigation finishes, so the two add
        up. If their sum exceeds the source ceiling, the harvester kills the
        scrape mid-draw - which is the same failure as a short goto, just
        arrived at by arithmetic instead of by one number.
        """
        total = (S._GOTO_TIMEOUT_MS + S._FEED_TIMEOUT_MS) / 1000
        self.assertLessEqual(
            total, H._SOURCE_TIMEOUT_FAR,
            f"goto ({S._GOTO_TIMEOUT_MS/1000}s) plus the feed wait "
            f"({S._FEED_TIMEOUT_MS/1000}s) is {total}s, over the "
            f"{H._SOURCE_TIMEOUT_FAR}s a distant source is given")

    def test_the_feed_is_given_time_to_draw_after_the_html_arrives(self):
        """Navigation returning is not the businesses appearing.

        Measured: navigation finished in 2-4s on runs where the feed took
        until 24s or never drew at all. The HTML arrives early and the script
        that builds the results list is what runs slowly, so a feed wait
        tuned to "the page is already here" discards the actual work.
        """
        self.assertGreaterEqual(
            S._FEED_TIMEOUT_MS, 30_000,
            "the results feed needs tens of seconds to draw on a slow "
            "server; 12s was returning 0 businesses from a page that had "
            "them")


class RoundBudgetSanityTests(unittest.TestCase):
    """A patient limit must not become an unbounded one."""

    def test_a_single_round_cannot_consume_a_whole_default_hunt(self):
        """Patience is bounded by the hunt's time budget, not by one round.

        The reason a round may now take four minutes is that the alternative
        was zero leads. But a round that can outlast the hunt itself would
        mean a single wedged source produces one round and no report at all.
        """
        self.assertLess(
            H._ROUND_TIMEOUT, 600,
            "a round that may run ten minutes makes a hunt one long silence")

    def test_a_hunt_fits_enough_rounds_to_find_anything(self):
        """Patience has a price, and this is where it is paid.

        Each round tries one query template. One round finds a handful of
        businesses, most of which fail a gate, so a hunt that fits only two or
        three rounds cannot reach a useful target however patient it is - and
        it would report that as an exhausted market, which is the failure this
        whole exercise has been about.

        Checked against the MEASURED scrape time rather than the ceiling,
        because the ceiling is the bad case and the measurement is the normal
        one. At 126s a one-hour hunt fits about 28 rounds; the ceilings only
        bite when something is genuinely wrong.
        """
        rounds_when_working = H._DEFAULT_TIME_BUDGET // _SLOWEST_OBSERVED_SUCCESS
        self.assertGreaterEqual(
            rounds_when_working, 10,
            f"at the measured {_SLOWEST_OBSERVED_SUCCESS}s per scrape, a "
            f"{H._DEFAULT_TIME_BUDGET}s hunt fits only {rounds_when_working} "
            f"rounds - too few query templates to find leads")

        worst_case_rounds = H._DEFAULT_TIME_BUDGET // H._ROUND_TIMEOUT
        self.assertGreaterEqual(
            worst_case_rounds, 5,
            f"if every round hit its {H._ROUND_TIMEOUT}s ceiling the hunt "
            f"would manage {worst_case_rounds} rounds, which is not enough "
            f"to distinguish a slow market from an empty one")

    def test_the_timeout_round_limit_still_stops_a_dead_market(self):
        """Longer ceilings make giving up early more important, not less.

        With a 240s round, four dead rounds is sixteen minutes. The limit
        that stops consecutive all-source timeouts is what keeps a genuinely
        unreachable market from eating the budget.
        """
        self.assertLessEqual(
            H._TIMEOUT_ROUNDS_LIMIT * H._ROUND_TIMEOUT, 900,
            f"{H._TIMEOUT_ROUNDS_LIMIT} rounds at {H._ROUND_TIMEOUT}s each "
            f"is too long to wait before admitting nothing is answering")


if __name__ == "__main__":
    unittest.main(verbosity=2)
