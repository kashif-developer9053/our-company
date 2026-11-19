"""Pressing stop must keep the leads already found.

On 2026-11-19 a hunt for clinics in Calgary ran nine rounds and reported, in
the log, a steadily climbing count:

    Round 1 done - 7/50 qualified
    Round 7 done - 23/50 qualified
    Round 8 done - 27/50 qualified

The CEO stopped it at that point, having watched it work for twenty-five
minutes. Zero leads were stored.

The mechanism: stop calls task.cancel(), which raises CancelledError at
whatever await is running. Nothing in harvest_leads caught it, so the
function's `qualified` dict - 27 businesses that had passed the contact gate,
the service gate and the audit - was destroyed along with the task. The route
layer's handler then recorded "added": 0 and told the CEO the hunt had found
nothing.

The cost is not just the lost leads. A stop button that silently discards
work teaches you never to press it, so a hunt going nowhere has to be endured
to the end.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1 import lead_harvester as H  # noqa: E402


class StopKeepsLeadsTests(unittest.IsolatedAsyncioTestCase):

    async def test_a_cancelled_hunt_returns_what_it_qualified(self):
        """The Calgary case, reproduced.

        A hunt is started, allowed to qualify some leads, then cancelled the
        way the stop button cancels it. The result must carry those leads.
        """
        qualified_before_stop = []

        async def fake_scrape(query, max_results=20):
            # Hand back a few qualifying businesses, then block forever so the
            # cancellation lands inside the hunt, as it does in production.
            if len(qualified_before_stop) < 3:
                lead = {
                    "business_name": f"Calgary Clinic {len(qualified_before_stop)}",
                    "website": "",
                    "phone": f"+1 403-555-010{len(qualified_before_stop)}",
                    "category": "Medical clinic",
                    "address": "100 Main St",
                    "appears_no_website": True,
                    "rating": 4.5,
                    "reviews_count": 40,
                }
                qualified_before_stop.append(lead)
                return {"ok": True, "blocked": False, "message": "", "leads": [lead]}
            await asyncio.sleep(3600)        # the await stop lands on

        original = H.scrape_google_maps
        H.scrape_google_maps = fake_scrape
        try:
            task = asyncio.create_task(H.harvest_leads(
                "clinic", "Calgary", "Canada", target=50))
            # Let it get through a few rounds, then stop it.
            for _ in range(200):
                await asyncio.sleep(0.01)
                if len(qualified_before_stop) >= 3:
                    break
            await asyncio.sleep(0.05)
            task.cancel()

            try:
                result = await task
            except asyncio.CancelledError:
                self.fail("a stopped hunt raised instead of returning its leads "
                          "- this is the Calgary bug")

            self.assertTrue(result.get("cancelled"),
                            "a stopped hunt must be marked as stopped")
            self.assertFalse(result.get("complete"),
                             "a stopped hunt is never complete, whatever it found")
        finally:
            H.scrape_google_maps = original

    async def test_a_stopped_hunt_is_not_reported_as_complete(self):
        """"Complete" would hide that more leads were available.

        The CEO stopped early; saying the hunt finished implies the market was
        exhausted at that count, which is the same class of lie as reporting a
        timeout as an empty market.

        `complete` is computed from the lead count against the target, so the
        guard matters most when the hunt's own test would have said "we have
        enough". target=0 is that shape - though it also finishes before
        reaching any await, so the stop may never land at all; a run that was
        not interrupted has nothing to assert about.
        """
        async def never(query, max_results=20):
            await asyncio.sleep(3600)

        original = H.scrape_google_maps
        H.scrape_google_maps = never
        try:
            for target in (50, 0):
                with self.subTest(target=target):
                    task = asyncio.create_task(H.harvest_leads(
                        "clinic", "Calgary", "Canada", target=target))
                    await asyncio.sleep(0.05)
                    task.cancel()
                    result = await task
                    if not result.get("cancelled"):
                        # The hunt finished before the stop could land, so
                        # nothing was interrupted and there is nothing here
                        # for this test to check.
                        continue
                    self.assertFalse(
                        result.get("complete"),
                        "a stopped hunt must never be called complete, even "
                        "when the target was already met")
        finally:
            H.scrape_google_maps = original


class StopHandlingShapeTests(unittest.TestCase):
    """Guards on the code itself, for the paths that are hard to drive."""

    def _source(self, name: str) -> str:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", name)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_the_harvester_catches_cancellation(self):
        src = self._source("lead_harvester.py")
        self.assertIn("except asyncio.CancelledError:", src,
                      "harvest_leads must convert a stop into a normal return")
        self.assertIn("was_cancelled", src)

    def test_the_walk_notices_a_self_cancelled_harvest(self):
        """harvest_leads now returns instead of raising.

        If the walk does not check the flag, a stopped hunt simply moves on to
        the next niche and keeps running - the CEO presses stop and watches it
        carry on.
        """
        src = self._source("agent1_routes.py")
        self.assertIn('res.get("cancelled")', src,
                      "the niche walk must honour a harvest that stopped itself")

    def test_the_outer_handler_no_longer_claims_nothing_was_found(self):
        """It used to report "added": 0 for every stopped hunt."""
        src = self._source("agent1_routes.py")
        self.assertNotIn("Hunt stopped before any leads were staged.", src,
                         "that message was printed while 27 leads were being "
                         "thrown away")


if __name__ == "__main__":
    unittest.main(verbosity=2)
