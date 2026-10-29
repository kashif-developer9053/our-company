"""A website hunt must return website leads, and nothing else.

Three separate bugs have now shipped that broke this, each from a fix aimed at
a different symptom:

  1. `_WEBSITE_FAULTS` was widened past the auditor's own `_QUALIFYING_CODES`,
     so a site with minor issues scored a "website" pitch while its evidence
     block read "their site is broadly fine".
  2. The good-site escape hatch in `qualifies()` applied to every hunt, so a
     website hunt collected photographers for CRM.
  3. A site we were blocked from checking was described as working.

Each assertion below is one of those, stated as the behaviour the CEO asked
for: "when i select web development then need to fetch not working site or no
sites leads".
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent1.purposes import _WEBSITE_FAULTS, diagnose          # noqa: E402
from agent1.service_targets import qualifies                    # noqa: E402
from agent1.site_auditor import _QUALIFYING_CODES               # noqa: E402


def lead(name="Studio", niche="wedding photographer", site="http://x.pk/",
         reviews=40, codes=(), qualified=False, unknown=False):
    audit = {"qualified": qualified, "summary": "audit summary",
             "findings": [{"code": c} for c in codes]}
    if unknown:
        audit["unknown"] = True
    return {"business_name": name, "niche": niche, "category": niche,
            "city": "islamabad", "website": site, "reviews_count": reviews,
            "site_audit": audit}


class WebsiteFaultSetTests(unittest.TestCase):
    def test_matches_the_auditors_own_verdict(self):
        """The two sets answer the same question and must not drift apart.

        When they disagree, a lead carries a label its own evidence denies.
        """
        self.assertEqual(_WEBSITE_FAULTS, _QUALIFYING_CODES)

    def test_cosmetic_faults_are_not_a_website_pitch(self):
        for code in ("no_https", "very_slow", "no_contact_route", "no_title",
                     "not_mobile_friendly", "no_h1", "no_meta_desc"):
            with self.subTest(code=code):
                self.assertNotIn(code, _WEBSITE_FAULTS)


class WebsiteHuntTests(unittest.TestCase):
    """sweep=False — the CEO named "website", so website is the answer."""

    def test_working_site_is_not_collected(self):
        fits, why = qualifies("website", lead(codes=("no_https", "very_slow")))
        self.assertFalse(fits)
        self.assertIn("website works", why)

    def test_no_website_is_collected(self):
        fits, _ = qualifies("website", lead(site="", codes=("no_website",),
                                            qualified=True))
        self.assertTrue(fits)

    def test_broken_site_is_collected(self):
        for code in ("http_error", "site_unreachable"):
            with self.subTest(code=code):
                fits, _ = qualifies("website", lead(codes=(code,), qualified=True))
                self.assertTrue(fits)

    def test_site_we_could_not_check_is_not_called_working(self):
        """403/429 means we saw nothing — so we claim nothing either way."""
        fits, why = qualifies("website", lead(codes=("blocked_to_us",), unknown=True))
        self.assertFalse(fits)
        self.assertIn("blocked", why)
        self.assertNotIn("works", why)

    def test_good_site_photographer_gets_no_website_purpose(self):
        """The exact lead the CEO objected to: label must not say Website."""
        self.assertNotIn("website",
                         diagnose(lead(codes=("no_https", "very_slow")),
                                  wanted="website"))


class AreaSweepTests(unittest.TestCase):
    """sweep=True — no service chosen, so a good site is not a rejection."""

    def test_good_site_kept_for_another_service(self):
        fits, why = qualifies("website", lead(codes=("no_https",)),
                              allow_other=True)
        self.assertTrue(fits)
        self.assertIn("site is fine", why)

    def test_kept_for_the_service_the_niche_signals(self):
        """A photographer kept on a sweep is kept for CRM, not for a website."""
        fits, why = qualifies("website", lead(codes=("no_https",)),
                              allow_other=True)
        self.assertTrue(fits)
        self.assertNotIn("website", diagnose(lead(codes=("no_https",))))

    @unittest.expectedFailure
    def test_business_we_can_sell_nothing_to_is_dropped(self):
        """KNOWN WEAKNESS, not caused by the website-hunt fix.

        `diagnose()` falls back to an "seo" purpose for any business that has
        a website and signals nothing else, so an area sweep keeps almost
        everything with "Search visibility" as the stated reason. That is a
        weak pitch and it pads the approval queue.

        Tightening it changes how much a sweep collects, which is the CEO's
        call on lead volume rather than a correctness fix, so it is recorded
        here instead of being changed quietly.
        """
        fits, _ = qualifies(
            "website",
            lead(name="Nondescript Office", niche="notary", reviews=2),
            allow_other=True)
        self.assertFalse(fits)


class NonWebsiteServiceTests(unittest.TestCase):
    def test_size_decides_not_the_audit(self):
        """A flawless site is no reason to reject a CRM prospect."""
        fits, _ = qualifies("crm", lead(reviews=40, qualified=False))
        self.assertTrue(fits)

    def test_too_big_is_rejected(self):
        fits, why = qualifies("crm", lead(reviews=5000))
        self.assertFalse(fits)
        self.assertIn("cold message", why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
