"""A hunt must not silently stop using its sources.

The harvester has five sources. Two optimisations exist to stop it grinding
for an hour on a town whose Maps results are exhausted:

  * skip the web crawler once Maps starts repeating itself;
  * run the social search only once per hunt.

Both were too aggressive, and the failure was invisible: the hunt still
reported success, having quietly run on Maps alone. Re-hunting a town whose
businesses were already in the CRM made round 1 barren immediately, which

  * skipped the crawler from round 1 onward, so it never ran at all; and
  * skipped the social search, which only ever runs in round 1 — and that is
    the source that finds businesses with NO WEBSITE, the strongest website
    pitch there is.

Simulated on a re-hunt (Maps returns only known businesses, crawler finds 3,
social finds 5): 0 leads before, 8 after.

These tests pin the rules in the source rather than the behaviour of the live
scrapers, which need the network.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

HARVESTER = (BACKEND_DIR / "agent1" / "lead_harvester.py").read_text(encoding="utf-8")


class SocialSearchTests(unittest.TestCase):
    """The no-website source must not depend on what Maps returned."""

    def test_social_search_is_not_gated_on_a_barren_maps_round(self):
        m = re.search(r"if rounds_run == 1 and not sweep:", HARVESTER)
        self.assertIsNotNone(
            m,
            "The social search guard changed. It must stay independent of "
            "maps_was_barren: Maps repeating itself says nothing about "
            "Facebook, and gating this meant the one source that finds "
            "businesses with no website never ran in a small town.")

    def test_social_guard_does_not_mention_maps_barren(self):
        """Catch the gate being reintroduced in any spelling."""
        guard = re.search(
            r"if rounds_run == 1 and not sweep[^\n]*:", HARVESTER)
        self.assertNotIn("maps_was_barren", guard.group(0))


class WebCrawlerTests(unittest.TestCase):
    def test_crawler_is_never_skipped_on_the_first_round(self):
        """Maps can repeat itself immediately; bailing then is too early."""
        guard = re.search(
            r"if not sweep and not \(maps_was_barren[^)]*\)", HARVESTER)
        self.assertIsNotNone(guard, "web crawler guard not found")
        self.assertIn(
            "rounds_run > 1", guard.group(0),
            "The crawler must run at least once before the barren-Maps skip "
            "applies, or it never runs at all when round 1 is already barren.")


class ExhaustedTownProtectionTests(unittest.TestCase):
    """The hour-long-grind fix must survive the loosened skips."""

    def test_barren_limits_are_still_in_place(self):
        from agent1.lead_harvester import (_BARREN_LIMIT, _BARREN_LIMIT_THIN,
                                           _ROUND_TIMEOUT, _SOURCE_TIMEOUT)
        self.assertLessEqual(_BARREN_LIMIT_THIN, 8)
        self.assertLessEqual(_BARREN_LIMIT, 8)
        self.assertLessEqual(_SOURCE_TIMEOUT, 120)
        self.assertLessEqual(_ROUND_TIMEOUT, 300)

    def test_a_dead_town_still_gives_up(self):
        """With every round barren, the hunt must stop within the limit."""
        from agent1.lead_harvester import _BARREN_LIMIT_THIN
        barren = rounds = 0
        for rounds in range(1, 100):
            barren += 1                      # nothing new, ever
            if barren >= _BARREN_LIMIT_THIN:
                break
        self.assertLessEqual(
            rounds, 10,
            "A town with nothing left must be abandoned in a few rounds, not "
            "ground on for an hour.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
