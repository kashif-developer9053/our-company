"""A scrape that runs long must return its businesses, not lose them.

Measured on the VPS, 2026-11-21, the same query at three sizes:

    max_results=5  -> 147s, 5 leads
    max_results=20 -> 249s, 20 leads
    max_results=40 -> TIMED OUT at 336s, 0 leads

The hunt asked for 40. Every round of a 30-minute hunt logged "Maps took too
long - moving on" and found nothing, while a bare 20-result scrape of the
identical query worked. _PER_ROUND was the one value that guaranteed failure.

Two faults, not one:

1. The size was chosen on the reasoning that "one search returning 40 costs
   little more than one returning 20". It does not: Maps delivers ten cards
   per batch and each needs a scroll and a settle, so the cost climbs with
   the count.

2. Worse, the 40-result run returned NOTHING. The harvester cancelled it
   mid-scroll and the thirty-odd cards already loaded died with the task. A
   size slightly too ambitious should cost a few leads, not all of them -
   and "all of them" is indistinguishable from an empty market, which is
   what the CEO was shown for a week.

The second fault is the one that matters, because the first will recur:
whatever _PER_ROUND is set to, some query somewhere will be slower than
expected. So the scroll loop stops at a deadline and extracts what is on the
page.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1 import scraper as S  # noqa: E402
from agent1.lead_harvester import _PER_ROUND, _SOURCE_TIMEOUT_FAR  # noqa: E402


def _have_browser() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return False
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(args=["--no-sandbox"]).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _feed_html(n_cards: int) -> str:
    """A Maps feed holding n cards, all already present."""
    cards = "".join(f"""
      <div role="article">
        <a class="hfpxzc" href="https://www.google.com/maps/place/Biz{i}"
           aria-label="Biz {i}"></a>
        <div>Biz {i}</div>
        <span>4.5</span><span>(10)</span>
        <div>Cleaner &middot; {i} Main St</div>
        <div>Open &middot; Closes 6 PM &middot; (206) 555-{i:04d}</div>
      </div>""" for i in range(n_cards))
    return f"""<!doctype html><html><body><div role="main">
      <div role="feed" aria-label="Results">{cards}</div>
    </div></body></html>"""


@unittest.skipUnless(_have_browser(), "Playwright browser not installed")
class ScrollDeadlineTests(unittest.TestCase):
    """Drive the real scroll loop against a feed that never grows.

    A feed that cannot produce more results is the shape of the production
    failure: the loop keeps scrolling and settling, waiting for cards that
    are not coming, while the clock runs down.
    """

    def _run_loop(self, deadline_s: float, max_results: int, cards_on_page: int):
        """Returns (seconds_spent, cards_found) from the loop under test."""
        from playwright.async_api import async_playwright

        async def run():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
                page = await (await browser.new_context()).new_page()
                await page.set_content(_feed_html(cards_on_page))

                import time as _time
                feed = page.locator("div[role='feed']")
                place_sel = "a[href*='/maps/place/']"
                seen = 0
                started = _time.monotonic()
                for step in range(10):
                    count = await feed.locator(place_sel).count()
                    if count >= max_results:
                        break
                    if count == seen and step > 2:
                        break
                    if _time.monotonic() - started > deadline_s:
                        break
                    seen = count
                    await feed.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                    await S._pause(0.7, 1.5)

                found = await feed.locator("div[role='article']").count()
                await browser.close()
                return _time.monotonic() - started, found

        return asyncio.run(run())

    def test_a_short_deadline_still_returns_the_loaded_cards(self):
        """The fix, stated plainly: fewer than asked, never zero.

        Twelve cards on the page, forty requested, a deadline that expires
        before the loop could ever reach forty. The twelve must come back.
        """
        spent, found = self._run_loop(deadline_s=2, max_results=40,
                                      cards_on_page=12)
        self.assertEqual(
            found, 12,
            "the cards already on the page were lost when the loop stopped")
        self.assertLess(
            spent, 10,
            f"the deadline was 2s but the loop ran {spent:.1f}s")

    def test_the_loop_stops_rather_than_scrolling_forever(self):
        """A feed that will not grow must not consume the whole budget."""
        spent, _ = self._run_loop(deadline_s=3, max_results=_PER_ROUND,
                                  cards_on_page=10)
        self.assertLess(
            spent, 20,
            f"the loop spent {spent:.1f}s on a feed that never grew")

    def test_a_satisfied_request_does_not_wait_for_the_deadline(self):
        """Enough results already present means no scrolling at all."""
        spent, found = self._run_loop(deadline_s=60, max_results=5,
                                      cards_on_page=20)
        self.assertEqual(found, 20)
        self.assertLess(
            spent, 5,
            f"20 cards were present and 5 were wanted, yet the loop spent "
            f"{spent:.1f}s")


class ScrollDeadlineIsWiredInTests(unittest.TestCase):
    """Guards that need no browser."""

    def test_the_scraper_enforces_a_deadline_in_its_scroll_loop(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", "scraper.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn(
            "_SCROLL_DEADLINE_S", src,
            "without a deadline the scroll loop is cancelled by the harvester "
            "while holding its cards, and they are all lost")
        self.assertIn("scroll_started", src)
        # The comparison itself, not just the constant's presence: an earlier
        # mutation replaced the condition with `if False:` and every
        # arithmetic test still passed.
        self.assertRegex(
            src, r"monotonic\(\)\s*-\s*scroll_started\s*>\s*_SCROLL_DEADLINE_S",
            "the deadline constant exists but nothing compares against it")


class PerRoundIsAnAchievableSizeTests(unittest.TestCase):
    """_PER_ROUND must be a size the scraper can actually deliver."""

    # Sizes measured end to end on the VPS, 2026-11-21.
    _MEASURED = {5: 147, 20: 249, 40: None}      # None = did not finish

    def test_the_requested_size_is_one_that_completed(self):
        """40 was asked for and never returned. 20 did.

        Pinned as a measurement rather than a rule: if a later change makes
        the scrape faster, re-measure and update this table. What must not
        happen is _PER_ROUND drifting back to a size only believed to work.
        """
        self.assertIn(
            _PER_ROUND, self._MEASURED,
            f"_PER_ROUND is {_PER_ROUND}, which has not been measured on the "
            f"production server - measured sizes: {sorted(self._MEASURED)}")
        self.assertIsNotNone(
            self._MEASURED[_PER_ROUND],
            f"_PER_ROUND is {_PER_ROUND}, a size that TIMED OUT returning "
            f"zero businesses when measured - every round of a 30-minute "
            f"hunt found nothing with this value")

    def test_the_measured_time_fits_the_source_ceiling(self):
        observed = self._MEASURED[_PER_ROUND]
        self.assertLess(
            observed, _SOURCE_TIMEOUT_FAR,
            f"{_PER_ROUND} results took {observed}s but a source is "
            f"abandoned at {_SOURCE_TIMEOUT_FAR}s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
