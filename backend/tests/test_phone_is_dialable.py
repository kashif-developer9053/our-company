"""A stored phone number must be dialable from where it will be dialled.

The same Seattle query returned phones in two different shapes minutes apart,
from two machines running the same commit:

    developer machine:  "+1 206-608-2614"
    VPS:                "(206) 608-2614"

Google prints a phone the way the country writes it, and which way depends on
the layout it serves. Nothing downstream normalised either, so whatever shape
arrived went into the CRM and on to Agent 3.

"(206) 608-2614" is not wrong, it is incomplete. It dials from inside the US
and fails from Pakistan, which is where it would actually be dialled from. For
the one job the field has, a number that cannot be rung is the same as no
number - and worse than an empty field, because an empty field is visibly
missing while this one looks fine until someone tries it.

The country is passed in explicitly rather than inferred from the query text.
An earlier version of this change passed the whole query string, and
"Landscapers in Seattle, United States" worked by luck: the table matched the
first country name it found, so a query mentioning two places would stamp a US
number with a Pakistani code. That bug is pinned below.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1.scraper import _build_lead, normalise_phone  # noqa: E402


class PhoneNormalisationTests(unittest.TestCase):

    def test_the_vps_format_becomes_internationally_dialable(self):
        """The exact string the server returned, and what it must become."""
        self.assertEqual(
            normalise_phone("(206) 608-2614", "United States"),
            "+1 206-608-2614")

    def test_an_already_international_number_is_left_alone(self):
        """Do not re-stamp what is already correct."""
        for already in ("+1 206-608-2614", "+92 322 3368251",
                        "+44 20 7946 0958", "+971 4 395 5591"):
            with self.subTest(phone=already):
                self.assertEqual(normalise_phone(already, "United States"),
                                 already)

    def test_a_trunk_prefix_is_replaced_not_kept(self):
        """"+44 020 ..." is not a phone number.

        The leading 0 means "another city in this country" and is what the
        country code replaces. Keeping both produces a number that looks
        plausible and does not connect.
        """
        self.assertEqual(normalise_phone("020 7946 0958", "United Kingdom"),
                         "+44 20-7946-0958")
        self.assertEqual(normalise_phone("0322 3368251", "Pakistan"),
                         "+92 322-3368251")

    def test_readability_survives(self):
        """A wall of digits is a lead a human cannot check at a glance.

        The CEO reviews these before Agent 3 calls anyone, so the grouping
        Google chose is reused rather than discarded: "+1 2066082614" is
        dialable and unreadable.
        """
        self.assertEqual(normalise_phone("(253) 656-4726", "United States"),
                         "+1 253-656-4726")
        self.assertEqual(normalise_phone("(416) 555-0199", "Canada"),
                         "+1 416-555-0199")

    def test_a_one_digit_area_code_is_handled(self):
        """Area codes run from one digit to four; the UAE is the short case."""
        self.assertEqual(
            normalise_phone("04 395 5591", "United Arab Emirates"),
            "+971 4-395-5591")

    def test_a_number_already_carrying_its_code_is_not_doubled(self):
        """"92 322 ..." must not become "+92 92 322 ..."."""
        out = normalise_phone("92 322 3368251", "Pakistan")
        self.assertTrue(out.startswith("+92 "), out)
        self.assertEqual(out.count("92"), 1, f"country code doubled: {out}")


class PhoneSafetyTests(unittest.TestCase):
    """What must NOT happen. Inventing a number is worse than keeping a bad one."""

    def test_an_unknown_country_leaves_the_number_untouched(self):
        """Do not guess a code from the digits."""
        for country in ("", "Atlantis", "Unknown", None):
            with self.subTest(country=country):
                self.assertEqual(
                    normalise_phone("(206) 608-2614", country),
                    "(206) 608-2614")

    def test_junk_is_returned_unchanged(self):
        for junk in ("", "   ", "abc", "-", "n/a"):
            with self.subTest(junk=junk):
                self.assertEqual(normalise_phone(junk, "United States"),
                                 junk.strip())

    def test_a_number_too_short_to_be_real_is_not_decorated(self):
        """Stamping "+1 " onto "1234" makes nonsense look official."""
        self.assertEqual(normalise_phone("1234", "United States"), "1234")


class CountryComesFromTheCallerTests(unittest.TestCase):
    """The bug introduced while wiring this up, pinned so it cannot return."""

    def test_the_country_is_not_inferred_from_a_query_string(self):
        """Passing the query as the country stamped a US number with +92.

        _build_lead takes the country, not the search text. If someone passes
        a query again, a search phrased across two places silently mislabels
        every phone in it - and a wrong country code is undetectable in the
        CRM until a call fails.
        """
        lead = _build_lead(
            "Test Co", "Landscaper · 1 Main St", "(206) 608-2614", "",
            country="United States")
        self.assertEqual(lead["phone"], "+1 206-608-2614")

        # The shape of the old bug: a query naming Pakistan, US digits.
        wrong = _build_lead(
            "Test Co", "x", "(206) 608-2614", "",
            country="clinic in Lahore, Pakistan")
        self.assertNotEqual(
            wrong["phone"], "+1 206-608-2614",
            "a query string was accepted as a country - this test exists to "
            "document that the parameter means COUNTRY, so callers must not "
            "pass the query")

    def test_the_harvester_passes_a_country_to_the_scraper(self):
        """A guard on the wiring, which no unit test of the pure function sees."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", "lead_harvester.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn(
            "country=country", src,
            "the harvester knows the country and must hand it to the scraper, "
            "or every phone stays in whatever local format Maps printed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
