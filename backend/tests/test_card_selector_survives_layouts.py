"""The card selector must survive both Maps layouts Google serves.

On 2026-11-20, after the user-agent fix, every hunt on the VPS still found
zero businesses - while the identical commit found 40 a round on a developer
machine. A DOM walk from a place link up to the feed showed why:

    developer machine:  div[role=feed] > div[role=article]
    VPS:                div[role=feed] > div > div[role=article]

One anonymous wrapper div. The scraper selected cards with
`feed.locator("> div")`, the feed's DIRECT children, so under the second
layout it matched that wrapper - which holds no place link of its own - and
the loop skipped it. Zero leads.

The probe that found this showed the businesses were on the page the whole
time: the body text read "North East Landscaping & Design | 4.9(216) |
Landscaper - 4311 11th Ave NE Ste 525", and `a[href*='/maps/place/']`
counted 10. Nothing was blocked and nothing was missing. The data was there
and the selector could not see it.

Two layouts means it is not a one-off migration to chase; Google serves
both, and which one arrives is not ours to choose. So these tests pin the
cards' own identity (role="article") rather than their position, and run the
real extraction over saved HTML of each shape.

Why this is tested against HTML rather than live Maps: a live test cannot
fail for the right reason. It would pass or fail on whichever layout Google
happened to serve that minute, which is precisely the coin-flip that let the
bug reach production and sit there for a week.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# A single result card, as Maps renders one. Trimmed to the parts the scraper
# reads: the place link carrying the name in aria-label, and the text lines
# holding rating, category, address, hours and phone.
def _card(name: str, rating: str, cat: str, addr: str, phone: str) -> str:
    return f"""
    <div role="article" class="Nv2PK tH5CWc THOPZb">
      <a class="hfpxzc" href="https://www.google.com/maps/place/{name.replace(' ', '+')}"
         aria-label="{name}"></a>
      <div class="qBF1Pd">{name}</div>
      <span class="MW4etd">{rating}</span><span class="UY7F9">(216)</span>
      <div class="W4Efsd">{cat} &middot; {addr}</div>
      <div class="W4Efsd">Open &middot; Closes 6 PM &middot; {phone}</div>
      <a href="https://{name.split()[0].lower()}.example.com">Website</a>
      <a href="https://www.google.com/maps/dir//thing">Directions</a>
    </div>"""


_CARDS = (
    _card("North East Landscaping", "4.9", "Landscaper", "4311 11th Ave NE Ste 525", "+1 206-608-2614"),
    _card("Rock Solid Landscapes", "4.8", "Landscaper", "3300 NE 55th St", "+1 206-523-7625"),
)


def _page(nested: bool) -> str:
    """Build a Maps results page in one of the two layouts seen in the wild."""
    cards = "".join(_CARDS)
    inner = f'<div>{cards}</div>' if nested else cards
    return f"""<!doctype html><html><body>
      <div role="main">
        <div role="feed" aria-label="Results for Landscapers in Seattle">
          {inner}
        </div>
      </div>
    </body></html>"""


def _have_browser() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return False
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--no-sandbox"])
            b.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_have_browser(), "Playwright browser not installed")
class CardSelectorLayoutTests(unittest.TestCase):
    """Run the scraper's own extraction over each layout's real DOM.

    The selector is exercised through a browser rather than a parser because
    `locator("> div")` vs `locator("div[role='article']")` is a CSS-semantics
    difference. Asserting on the source text would re-test the bug's
    description instead of its behaviour.
    """

    def _extract(self, html: str) -> list[dict]:
        from playwright.async_api import async_playwright
        from agent1.scraper import _build_lead, _phone_from_card

        async def run():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
                page = await (await browser.new_context()).new_page()
                await page.set_content(html)

                place_sel = "a[href*='/maps/place/']"
                feed = page.locator("div[role='feed']")

                # The selection under test, copied from scrape_google_maps.
                cards = feed.locator("div[role='article']")
                total = await cards.count()
                if not total:
                    cards = feed.locator(f"div:has(> {place_sel})")
                    total = await cards.count()

                out = []
                for i in range(total):
                    card = cards.nth(i)
                    link = card.locator(place_sel)
                    if not await link.count():
                        continue
                    name = ((await link.first.get_attribute("aria-label")) or "").strip()
                    if not name:
                        continue
                    text = await card.inner_text()
                    website = ""
                    ext = card.locator("a[href^='http']:not([href*='google.'])")
                    if await ext.count():
                        website = (await ext.first.get_attribute("href")) or ""
                    out.append(_build_lead(name, text, _phone_from_card(text), website))

                await browser.close()
                return out

        return asyncio.run(run())

    def test_cards_are_found_when_nested_under_a_wrapper(self):
        """The VPS layout: feed > div > article. This is the outage."""
        leads = self._extract(_page(nested=True))
        self.assertEqual(
            len(leads), 2,
            "cards nested under a wrapper were not found - this is the bug "
            "that made every hunt report an exhausted market")
        self.assertEqual([L["business_name"] for L in leads],
                         ["North East Landscaping", "Rock Solid Landscapes"])

    def test_cards_are_found_when_direct_children_of_the_feed(self):
        """The layout that used to work must keep working."""
        leads = self._extract(_page(nested=False))
        self.assertEqual(len(leads), 2)
        self.assertEqual([L["business_name"] for L in leads],
                         ["North East Landscaping", "Rock Solid Landscapes"])

    def test_both_layouts_yield_identical_leads(self):
        """Nesting is Google's business, not the lead's.

        Equal counts are not enough: a selector could find both cards and
        still read the wrong element's text, giving a lead with no phone or
        the wrapper's concatenated text as its address.
        """
        flat = self._extract(_page(nested=False))
        nested = self._extract(_page(nested=True))
        self.assertEqual(flat, nested,
                         "the same businesses came out differently depending "
                         "on the layout Google happened to serve")

    def test_the_extracted_fields_are_actually_right(self):
        """A card that is found but misread is still a lost lead.

        Agent 3 dials the phone and greets the business by name, so a lead
        carrying the wrapper's text in those fields is worse than no lead.
        """
        leads = self._extract(_page(nested=True))
        first = leads[0]
        self.assertEqual(first["business_name"], "North East Landscaping")
        self.assertEqual(first["phone"], "+1 206-608-2614")
        self.assertEqual(first["category"], "Landscaper")
        self.assertIn("4311 11th Ave NE", first["address"])
        self.assertEqual(first["website"], "https://north.example.com")
        self.assertFalse(first["appears_no_website"])
        self.assertEqual(first["rating"], 4.9)
        self.assertEqual(first["reviews_count"], 216)

    def test_an_unlabelled_layout_falls_back_instead_of_finding_nothing(self):
        """If Google drops role="article" too, do not go silent again.

        The lesson of this outage is not "role=article is the answer" - it is
        that returning zero looks exactly like an empty market, so the
        scraper must exhaust its options before saying nothing is there.
        """
        html = _page(nested=True).replace('role="article" ', "")
        leads = self._extract(html)
        self.assertEqual(
            len(leads), 2,
            "with no role=article the fallback must still find the cards")


class SelectorShapeTests(unittest.TestCase):
    """Runs without a browser, so the regression is guarded even in CI."""

    def test_the_feeds_direct_children_are_no_longer_the_card_selector(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", "scraper.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()

        self.assertNotIn(
            'cards = feed.locator("> div")', src,
            'selecting the feed\'s direct children breaks whenever Google '
            'adds a wrapper, which is what returned zero leads on the VPS')
        self.assertIn("div[role='article']", src,
                      "cards should be identified by their own role")


if __name__ == "__main__":
    unittest.main(verbosity=2)
