"""City/country pairs that cannot be right must never reach the scraper.

The CEO ran a hunt on "Islamabad, India". Nothing objected: the scraper
searched that string, Google Maps returned nothing useful, and the hunt
reported no leads. The wasted few minutes are the small loss. The real loss is
the conclusion it invites — that the market is empty — which is both false and
expensive to act on.

The fix the CEO asked for is a suggestion, not an error: type a city and the
country fills itself in, so the bad pair cannot be produced. These tests cover
the data behind that, plus the backend guard for anything that bypasses the
form (the API directly, a stale cached page, a saved search).

The guiding rule is that silence is the default. This gazetteer is small by
design, and a hunt must never be blocked because a legitimate town is missing
from it.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1.locations import (AMBIGUOUS, CITY_COUNTRY, country_for,  # noqa: E402
                              known_cities, mismatch, suggest)


class LocationTests(unittest.TestCase):

    def test_the_ceos_actual_mistake_is_caught(self):
        """'Islamabad, India' — the case that prompted this."""
        problem = mismatch("Islamabad", "India")
        self.assertTrue(problem, "Islamabad/India must be refused")
        self.assertIn("Pakistan", problem, "the message must name the right country")

    def test_city_suggests_its_country(self):
        """Typing a city fills the country in — the feature as asked for."""
        for city, expected in [("Islamabad", "Pakistan"), ("Lahore", "Pakistan"),
                               ("Karachi", "Pakistan"), ("Murree", "Pakistan"),
                               ("Dubai", "United Arab Emirates"),
                               ("London", "United Kingdom"), ("Delhi", "India")]:
            with self.subTest(city=city):
                self.assertEqual(suggest(city)["country"], expected)

    def test_matching_ignores_case_and_spacing(self):
        """A city typed in haste must still be recognised."""
        for messy in ["islamabad", "ISLAMABAD", "  Islamabad  ", "islamabad "]:
            with self.subTest(messy=messy):
                self.assertEqual(country_for(messy), "Pakistan")

    def test_correct_pairs_are_never_blocked(self):
        """False positives are worse than misses: they stop real work."""
        for city, country in [("Islamabad", "Pakistan"), ("Lahore", "pakistan"),
                              ("Karachi", "PAKISTAN"), ("Dubai", "UAE"),
                              ("Dubai", "United Arab Emirates"),
                              ("London", "UK"), ("London", "England"),
                              ("New York", "USA"), ("Delhi", "India"),
                              ("Toronto", "Canada")]:
            with self.subTest(pair=(city, country)):
                self.assertEqual(mismatch(city, country), "",
                                 f"{city}/{country} is correct and must pass")

    def test_unknown_cities_never_block_a_hunt(self):
        """The gazetteer is small; a town missing from it is not an error.

        Pakistan has thousands of towns worth hunting. Blocking the ones this
        file has not heard of would make the feature a liability.
        """
        for city in ["Chak 42 Jhumra", "Nowhereville", "Kot Addu Extension", ""]:
            with self.subTest(city=city):
                self.assertEqual(mismatch(city, "Pakistan"), "")
                self.assertEqual(mismatch(city, "India"), "")

    def test_ambiguous_cities_do_not_guess(self):
        """Hyderabad is in BOTH Pakistan and India.

        Guessing would present a coin flip as a fact, so these suggest nothing
        and never object to whatever the CEO types.
        """
        for city in ["Hyderabad", "Birmingham", "Newcastle"]:
            with self.subTest(city=city):
                s = suggest(city)
                self.assertTrue(s["ambiguous"], f"{city} must be marked ambiguous")
                self.assertEqual(s["country"], "", "an ambiguous city must not autofill")
                self.assertEqual(mismatch(city, "India"), "")
                self.assertEqual(mismatch(city, "Pakistan"), "")

    def test_empty_input_is_silent(self):
        """A half-typed form must not shout at the CEO."""
        self.assertEqual(mismatch("", "Pakistan"), "")
        self.assertEqual(mismatch("Islamabad", ""), "")
        self.assertEqual(mismatch("", ""), "")

    def test_home_market_is_covered(self):
        """Pakistan is where we sell, so its coverage must be real."""
        pk = [c for c in CITY_COUNTRY if CITY_COUNTRY[c] == "Pakistan"]
        self.assertGreater(len(pk), 50,
                           "the home market needs more than a token few cities")
        # The ones a hunt would plausibly name.
        for city in ["islamabad", "lahore", "karachi", "rawalpindi", "faisalabad",
                     "multan", "peshawar", "quetta", "gujranwala", "sialkot",
                     "murree", "abbottabad", "bahawalpur", "sargodha"]:
            with self.subTest(city=city):
                self.assertEqual(CITY_COUNTRY.get(city), "Pakistan")

    def test_ambiguous_entries_are_real_entries(self):
        """A typo in AMBIGUOUS would silently disable a city's suggestion."""
        for city in AMBIGUOUS:
            with self.subTest(city=city):
                self.assertIn(city, CITY_COUNTRY,
                              f"'{city}' is marked ambiguous but is not in the map")

    def test_keys_are_normalised(self):
        """Lookup normalises the input, so the keys must already be normal."""
        for key in CITY_COUNTRY:
            with self.subTest(key=key):
                self.assertEqual(key, key.strip().lower(),
                                 "keys must be lowercase and unpadded")
                self.assertNotIn("  ", key, "no double spaces in keys")

    def test_known_cities_is_usable_by_the_form(self):
        """The datalist the form renders."""
        cities = known_cities()
        self.assertGreater(len(cities), 100)
        self.assertEqual(cities, sorted(cities), "must be sorted for the dropdown")
        self.assertIn("Islamabad", cities)
        self.assertIn("Lahore", cities)


if __name__ == "__main__":
    unittest.main(verbosity=2)
