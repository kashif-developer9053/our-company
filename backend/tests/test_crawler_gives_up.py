"""A source that never answers must stop being asked.

On 2026-11-19 a hunt for interior designers in Seattle ran 18 rounds across a
full hour. Every round contained this pair of lines, exactly 140 seconds
apart:

    Round N: checking published websites...
    Round N: web crawl took too long - moving on.

140s is _SOURCE_TIMEOUT_FAR, the whole ceiling, 18 times: roughly 42 minutes
of a 60-minute hunt spent waiting on a source that never once answered. Maps,
meanwhile, was returning 23-40 businesses every round in under a minute.

This drives the real harvest_leads and counts how often the crawler is
actually called, rather than restating the rule - a previous version of this
test asserted that the text "crawl_timeouts = 0" appeared in the source,
which it does twice, so deleting the reset left the test passing.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1 import lead_harvester as H  # noqa: E402


class CrawlerGiveUpTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self._scrape = H.scrape_google_maps
        self._mine = H.mine_business_websites
        self._enrich = H.enrich_lead_emails
        self._audit = H.audit_leads
        self._social = H.discover_social_businesses

    def tearDown(self):
        H.scrape_google_maps = self._scrape
        H.mine_business_websites = self._mine
        H.enrich_lead_emails = self._enrich
        H.audit_leads = self._audit
        H.discover_social_businesses = self._social

    def _stub_everything_but_the_crawler(self):
        """Maps keeps producing new businesses, so the hunt keeps looping."""
        counter = {"n": 0}

        async def maps(query, max_results=20):
            counter["n"] += 1
            i = counter["n"]
            return {"ok": True, "blocked": False, "message": "", "leads": [{
                "business_name": f"Studio {i}",
                "website": f"https://studio{i}.example.com",
                "phone": "", "category": "Interior designer",
                "address": "1 Main St", "appears_no_website": False,
                "rating": 4.5, "reviews_count": 20,
            }]}

        async def enrich(leads, concurrency=4):
            return 0

        async def audit(leads, concurrency=4, **kw):
            for L in leads:
                L["site_audit"] = {"ok": True, "qualified": False,
                                   "unknown": False, "findings": []}
            return leads

        async def social(*a, **k):
            return {"ok": False, "leads": []}

        H.scrape_google_maps = maps
        H.enrich_lead_emails = enrich
        H.audit_leads = audit
        H.discover_social_businesses = social

    async def test_a_crawler_that_never_answers_is_dropped(self):
        """The Seattle case: 18 rounds, 18 timeouts, 42 minutes wasted."""
        self._stub_everything_but_the_crawler()
        calls = {"n": 0}

        async def dead_crawler(query, max_results=40):
            calls["n"] += 1
            await asyncio.sleep(3600)        # never returns; wait_for kills it

        H.mine_business_websites = dead_crawler

        # A short per-source timeout keeps the test fast; the behaviour under
        # test is how MANY times the crawler is asked, not how long it waits.
        original = H._SOURCE_TIMEOUT_FAR
        H._SOURCE_TIMEOUT_FAR = 1
        try:
            await H.harvest_leads("interior design", "Seattle", "United States",
                                  target=50, time_budget=25)
        finally:
            H._SOURCE_TIMEOUT_FAR = original

        self.assertLessEqual(
            calls["n"], H._CRAWL_GIVE_UP_AFTER,
            f"the crawler was asked {calls['n']} times after failing every "
            f"time; it should stop after {H._CRAWL_GIVE_UP_AFTER}")
        self.assertGreaterEqual(
            calls["n"], 1, "the crawler must still be tried at least once")

    async def test_an_intermittent_crawler_keeps_being_used(self):
        """Fail, succeed, fail is a slow source, not a dead one.

        Giving up on it would lose the businesses Maps does not list, which is
        the whole reason the crawler exists. The strikes must be CONSECUTIVE.
        """
        self._stub_everything_but_the_crawler()
        calls = {"n": 0}

        async def flaky(query, max_results=40):
            calls["n"] += 1
            if calls["n"] % 2:               # odd calls hang, even ones answer
                await asyncio.sleep(3600)
            return {"ok": True, "leads": []}

        H.mine_business_websites = flaky

        original = H._SOURCE_TIMEOUT_FAR
        H._SOURCE_TIMEOUT_FAR = 1
        try:
            await H.harvest_leads("interior design", "Seattle", "United States",
                                  target=50, time_budget=25)
        finally:
            H._SOURCE_TIMEOUT_FAR = original

        self.assertGreater(
            calls["n"], H._CRAWL_GIVE_UP_AFTER,
            f"a crawler that answers every other round was dropped after "
            f"{calls['n']} calls - a success must clear the strike count")

    # NOTE on coverage, so the next person does not trust this further than
    # it goes. Deleting the `crawl_timeouts = 0` reset does NOT fail the test
    # above: with Maps stubbed to one business per round the hunt hits its
    # barren-round limit and stops before the alternating pattern has run
    # long enough to tell the two behaviours apart. The reset is covered by
    # test_hunt_sources_run.py, which replays the rule directly, and by the
    # _CRAWL_GIVE_UP_AFTER >= 2 assertion there. Driving it through the real
    # harvester would need a stub that keeps the hunt alive for a dozen
    # rounds, which is a bigger fixture than the risk justifies.


if __name__ == "__main__":
    unittest.main(verbosity=2)
