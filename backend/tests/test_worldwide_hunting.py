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

    def test_contact_details_come_from_the_results_page(self):
        """No per-business detail page. That stage was the entire cost.

        Timed on the VPS 2026-11-19, Lahore, 5 results:
            search page + feed ready ......  11s
            5 detail pages, 4 in parallel ..  30s   (24-28s EACH)

        Every tab took the same ~25s, so they were not queueing - each detail
        page is simply slow. That is why 2 tabs and 4 tabs measured identically
        (56s vs 57s avg, three runs each): parallelism was already saturated
        and there was nothing left for tuning to win.

        The results page already carries name, rating, reviews, category,
        address, phone and website for every business, so the whole stage was
        removable. One page load instead of one-per-business is also what makes
        distant hunting viable: distance is paid once, not N times.
        """
        src = self._source()
        self.assertIn("_phone_from_card", src,
                      "the phone must be read from the result card")
        self.assertNotIn(
            "_DETAIL_CONCURRENCY", src,
            "per-business detail pages are gone; the knob should go with them")
        self.assertNotIn(
            "await tab.goto(", src,
            "opening a tab per business is the 30s stage that was removed")

    def test_the_card_is_more_complete_than_the_detail_panel_was(self):
        """The old path also LOST data, which matters more than the speed.

        Of 5 detail panels, only 3 exposed a phone button, while all 8 cards
        in the same search showed a phone. Two businesses were being stored
        with no phone number that Google was displaying all along.
        """
        from agent1.scraper import _build_lead, _phone_from_card

        card = ("DH Dental Clinic\n"
                "DH Dental Clinic\n"
                "4.9(78)\n"
                "Dental clinic \u00b7  \u00b7 152 G1 Canal Rd\n"
                "Open \u00b7 Closes 6 PM \u00b7 +92 322 3368251\n\n"
                "Website\n\nDirections")
        lead = _build_lead("DH Dental Clinic", card,
                           _phone_from_card(card), "http://www.dh.dental/")
        self.assertEqual(lead["phone"], "+92 322 3368251")
        self.assertEqual(lead["category"], "Dental clinic")
        self.assertEqual(lead["address"], "152 G1 Canal Rd")
        self.assertEqual(lead["rating"], 4.9)
        self.assertEqual(lead["reviews_count"], 78)

    def test_the_category_is_not_the_business_name(self):
        """A card prints the business name TWICE, on lines 1 and 2.

        The old extractor skipped only line 1 and took the next short line
        with letters, so it returned the business name as the category for
        every lead in the database. The address was never read at all.
        """
        from agent1.scraper import _category_and_address

        for name, text, cat, addr in [
            ("Smile Hub Clinics",
             "Smile Hub Clinics\nSmile Hub Clinics\n4.8(237)\n"
             "Dentist \u00b7  \u00b7 599 Main Blvd\n"
             "Closes soon \u00b7 2 PM \u00b7 Reopens 6 PM \u00b7 +92 303 5995990",
             "Dentist", "599 Main Blvd"),
            ("Rahman and Rahman Dental Surgeons Packages Mall",
             "Rahman and Rahman Dental Surgeons Packages Mall\n"
             "Rahman and Rahman Dental Surgeons Packages Mall\n4.8(178)\n"
             "Dental clinic \u00b7 Shop #G-010, Packages Mall",
             "Dental clinic", "Shop #G-010, Packages Mall"),
            # A name containing a middle dot looks exactly like the
            # category/address line. Without the explicit name check this
            # returns "Smile" as the category and "Dental Lahore" as the
            # address - mutation testing found that the other two cases above
            # passed on the dot check alone, so this case is what actually
            # holds the name comparison in place.
            ("Smile \u00b7 Dental \u00b7 Lahore",
             "Smile \u00b7 Dental \u00b7 Lahore\nSmile \u00b7 Dental \u00b7 Lahore\n4.7(50)\n"
             "Dental clinic \u00b7 12 Mall Rd\nOpen \u00b7 Closes 7 PM",
             "Dental clinic", "12 Mall Rd"),
        ]:
            with self.subTest(name=name[:20]):
                got_cat, got_addr = _category_and_address(text, name)
                self.assertEqual(got_cat, cat)
                self.assertEqual(got_addr, addr)
                self.assertNotEqual(got_cat.lower(), name.lower(),
                                    "the category must never be the name")

    def test_the_hours_line_is_not_mistaken_for_the_category(self):
        """"Open / Closes 6 PM" sits on its own dotted line, like the category."""
        from agent1.scraper import _category_and_address

        cat, _ = _category_and_address(
            "X Clinic\nX Clinic\n4.1(9)\nOpen \u00b7 Closes 6 PM \u00b7 +92 300 1234567",
            "X Clinic")
        self.assertNotIn("clos", cat.lower())
        self.assertNotIn("open", cat.lower())

    def test_an_address_is_never_recorded_as_a_phone_number(self):
        """The card mixes phones with street numbers, ratings and hours.

        A lead carrying "Flat # 3, 1st Floor" in its phone field is worse than
        one with no phone: Agent 3 would try to dial it. No phone is the
        correct answer when Google did not show one.
        """
        from agent1.scraper import _phone_from_card

        for text in [
            "FAMILY DENTAL CLINIC\n4.8(25)\n"
            "Dental clinic \u00b7  \u00b7 Flat # 3, 1st Floor, Lahore \u2013 Kasur Rd\n"
            "Open \u00b7 Closes 9 PM",
            "Rating Only\n4.9(253)\nDental clinic \u00b7 Y Block, 267-Y Street 11",
            "No Phone Co\n3.9(4)\nClinic \u00b7  \u00b7 Plot 45-A, Block 12, Sector F-8\n"
            "Closed \u00b7 Opens 9 AM",
        ]:
            with self.subTest(text=text[:28]):
                self.assertEqual(_phone_from_card(text), "",
                                 "no phone shown means no phone stored")

    def test_phones_are_found_outside_pakistan(self):
        """Worldwide hunting means worldwide phone formats.

        A +92-only pattern would silently return no phone for every US, UK or
        Gulf lead, and the hunt would look like it was finding weak prospects
        rather than failing to parse them.
        """
        from agent1.scraper import _phone_from_card

        for text, want in [
            ("C\n4.2(1,204)\nClinic \u00b7 1234 Union Ave\nOpen \u00b7 Closes 5 PM \u00b7 +1 901-555-0134",
             "+1 901-555-0134"),
            ("C\n4.0(12)\nClinic \u00b7 5600 Poplar Ave Suite 200\nOpen \u00b7 (901) 555-0134",
             "(901) 555-0134"),
            ("C\n4.5(88)\nDentist \u00b7 10 Harley St\nOpen \u00b7 020 7946 0958",
             "020 7946 0958"),
            ("C\n4.6(31)\nClinic \u00b7 Jumeirah 1\nOpen \u00b7 +971 4 395 5591",
             "+971 4 395 5591"),
        ]:
            with self.subTest(want=want):
                self.assertEqual(_phone_from_card(text), want)

    def test_a_looser_pattern_still_rejects_real_addresses(self):
        """The guard against fixing the UAE bug by making the pattern vague.

        Widening the international branch to accept a one-digit area code
        (+971 4 ...) made it accept any 7-12 digit run after a "+". These are
        real Maps addresses, digit-heavy on purpose; if any of them parses as
        a phone number, Agent 3 dials a street address.
        """
        from agent1.scraper import _phone_from_card

        for addr in [
            "Flat # 3, 1st Floor, Lahore – Kasur Rd, beside qainchi Flyover",
            "Y Block, 267-Y Street 11",
            "Plot 45-A, Block 12, Sector F-8",
            "5600 Poplar Ave Suite 200",
            "House 12-B, Street 45, DHA Phase 5",
            "Office 1204, 12th Floor, Tower A",
            "Shop 7, Plaza 88, Main Blvd Gulberg III",
        ]:
            with self.subTest(addr=addr[:30]):
                card = ("Some Clinic\nSome Clinic\n4.5(60)\n"
                        f"Clinic · {addr}\nOpen")
                self.assertEqual(
                    _phone_from_card(card), "",
                    "an address must never be stored as a phone number")

    def test_a_bare_digit_run_is_not_treated_as_a_phone(self):
        """No "+", no bracketed area code, no trunk "0" means no phone.

        A loose "any long digit run" pattern is the obvious way to widen
        coverage and the wrong one: the card text is full of digit runs
        that are addresses. A number with no dialing prefix could not be
        called from Pakistan anyway, so rejecting it loses nothing.
        """
        from agent1.scraper import _phone_from_card

        for tail in ["322 3368251", "3223368251", "555 0134", "1204 5600"]:
            with self.subTest(tail=tail):
                card = ("X Clinic\nX Clinic\n4.0(5)\n"
                        f"Clinic \u00b7 Main Rd\nOpen \u00b7 {tail}")
                self.assertEqual(
                    _phone_from_card(card), "",
                    "a digit run with no dialing prefix is not a phone number")

    def test_icon_font_glyphs_never_reach_a_lead(self):
        """Maps draws card badges with an icon font, not with text.

        Captured live from the VPS on 2026-11-19, a real Lahore lead came
        back with address '\\ue934 152 G1 Canal Rd'. U+E934 is a Private
        Use Area codepoint - a glyph in Google's own font with no Unicode
        meaning - and it is NOT whitespace, so str.strip() leaves it in
        place. It would reach the CRM and the outreach email as a broken
        box, in the address and potentially in the business name that
        opens the email.
        """
        from agent1.scraper import _build_lead, _phone_from_card

        card = ("DH Dental Clinic\nDH Dental Clinic\n4.9(78)\n"
                "Dental clinic \u00b7 \ue934 \u00b7 152 G1 Canal Rd\n"
                "Open \u00b7 Closes 6 PM \u00b7 +92 322 3368251")
        lead = _build_lead("\ue934DH Dental Clinic", card,
                           _phone_from_card(card), "http://www.dh.dental/")

        for field in ("business_name", "category", "address", "phone"):
            with self.subTest(field=field):
                value = lead[field]
                self.assertFalse(
                    any(0xE000 <= ord(c) <= 0xF8FF for c in value),
                    f"{field}={value!r} still carries an icon-font glyph")
        self.assertEqual(lead["address"], "152 G1 Canal Rd")
        self.assertEqual(lead["business_name"], "DH Dental Clinic")

    def test_stripping_a_glyph_does_not_join_two_words(self):
        """A glyph between words stands for a space, not for nothing.

        Deleting it outright would turn "Wheelchair<glyph>accessible" into
        "Wheelchairaccessible", which is worse than the broken box because
        it looks like real text and would never be noticed.
        """
        from agent1.scraper import _strip_icon_glyphs

        self.assertEqual(
            _strip_icon_glyphs("Wheelchair\ue934accessible entrance"),
            "Wheelchair accessible entrance")
        self.assertEqual(_strip_icon_glyphs("\ue934"), "")
        self.assertEqual(_strip_icon_glyphs(""), "")
        self.assertEqual(_strip_icon_glyphs("\ue934 Main Rd"), "Main Rd")

    def test_googles_own_links_are_not_recorded_as_the_website(self):
        """A card contains Google links too (the place link, Directions).

        Recording one as the lead's website would point the site auditor at
        google.com and produce an audit of Google for every prospect.
        """
        src = self._source()
        self.assertRegex(
            src, r"a\[href\^='http'\]:not\(\[href\*='google\.'\]\)",
            "the website selector must exclude Google's own links")

    def test_heavy_resources_are_still_blocked(self):
        """Images, media and fonts are pure bytes we never read."""
        src = self._source()
        self.assertRegex(src, r'(?m)^\s*await context\.route\(',
                         "resource blocking must be installed, not commented out")


if __name__ == "__main__":
    unittest.main(verbosity=2)
