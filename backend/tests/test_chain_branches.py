"""A branch of a chain is not a prospect, in any country.

On 2026-11-19 a hunt for clinics in Seattle ran 13 rounds over 30+ minutes and
qualified nothing. Maps was working: it returned 21, 40, 23 and 40 businesses
per round. Every round ended the same way:

    0/100 qualified (4 no contact, 43 site already fine)

Looking at who those businesses actually were explains it. Ten of the twenty
results were branches of five organisations:

    uwmedicine.org             x2   (incl. "Harborview Medical Center")
    neighborcare.org           x2   (incl. "45th Street Clinic")
    pacificmedicalcenters.org  x2
    sihb.org                   x2
    seattleroots.org           x2   ("Country Doctor Community Clinic" and
                                     "After Hours Clinic" - no shared words)

They all passed every gate: the ICP list of institutions was written entirely
from Pakistani names, and the review-count gate could not help because a
BRANCH only accumulates its own reviews. Swedish Primary Care has 172, One
Medical 65, Neighborcare Pike Place 68 - far below the 1,500 threshold, and
indistinguishable from a real corner clinic by that measure alone.

The signal that does work needs no names: several different businesses
publishing the SAME website are locations of one group. The site belongs to
the group, so a branch cannot commission work on it, and the cold email
reaches someone with no authority over what is being pitched.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1.lead_harvester import _mark_chain_branches, _site_domain  # noqa: E402


def _leads(pairs):
    return [{"business_name": n, "website": w} for n, w in pairs]


# The real Seattle result set, captured from the VPS on 2026-11-19.
SEATTLE = [
    ("Acupuncture & Wellness Center", ""),
    ("CVS Pharmacy", ""),
    ("Downtown Public Health Center", "http://www.kingcounty.gov/depts/health/x"),
    ("Neighborcare Health at Pike Place Market", "https://neighborcare.org/a"),
    ("One Medical Primary Care Clinic - Downtown Seattle", "https://onemedical.com/x"),
    ("Dunia Health Clinic LLC", "https://www.duniahealthclinic.com/"),
    ("Klinic Medical, PLLC", "https://www.klinic.com/"),
    ("Seattle University Health Center", "https://www.seattleu.edu/student-health/"),
    ("Capitol Hill Medical", "http://www.capitolhillmedical.com/"),
    ("Swedish Primary Care - Downtown Seattle", "https://www.swedish.org/x"),
    ("Seattle Indian Health Board Pioneer Square Clinic", "https://sihb.org/a"),
    ("Harborview Medical Center", "https://www.uwmedicine.org/a"),
    ("45th Street Clinic", "https://neighborcare.org/b"),
    ("UW Medicine Pioneer Square Clinic", "https://www.uwmedicine.org/b"),
    ("ZoomCare Downtown Seattle", "https://zoomcare.com/"),
    ("Seattle Indian Health Board International District", "https://sihb.org/b"),
    ("PacMed Clinics, Northgate", "https://pacificmedicalcenters.org/a"),
    ("PacMed Clinics, Beacon Hill", "https://pacificmedicalcenters.org/b"),
    ("Country Doctor Community Clinic", "https://seattleroots.org/a"),
    ("After Hours Clinic- Seattle Roots", "https://seattleroots.org/b"),
]

# A real Lahore dental search. Every clinic is independent.
LAHORE = [
    ("DH Dental Clinic", "http://www.dh.dental/"),
    ("Smile Hub Clinics", "https://smilehubclinics.com/"),
    ("Rahman and Rahman Dental Surgeons", "https://rahmanandrahmanpackages.com/"),
    ("Dr Imran's Multispeciality Dental Care", "https://drimrandentalcare.com/"),
    ("FAMILY DENTAL CLINIC", "https://familydentallahore.com/"),
    ("Dental Avenue Hospital", "https://dentalavenue.pk/"),
    ("Teeth and Smile", "https://teethandsmile.pk/"),
    ("Cantt Dental Care", "https://canttdentalcare.com/"),
]


class ChainBranchTests(unittest.TestCase):

    def test_the_seattle_networks_are_caught(self):
        fresh = _leads(SEATTLE)
        _mark_chain_branches({}, fresh)
        flagged = {l["business_name"] for l in fresh if l.get("chain_branch")}
        for name in [
            "Harborview Medical Center",
            "UW Medicine Pioneer Square Clinic",
            "Neighborcare Health at Pike Place Market",
            "45th Street Clinic",
            "PacMed Clinics, Northgate",
            "PacMed Clinics, Beacon Hill",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, flagged)

    def test_it_works_without_knowing_any_brand_names(self):
        """The point of the whole approach.

        "Country Doctor Community Clinic" and "After Hours Clinic- Seattle
        Roots" share no word, no abbreviation and no obvious brand. Only the
        shared domain connects them. A hand-written list of health networks
        would never have contained either.
        """
        fresh = _leads(SEATTLE)
        _mark_chain_branches({}, fresh)
        by_name = {l["business_name"]: l for l in fresh}
        for name in ["Country Doctor Community Clinic",
                     "After Hours Clinic- Seattle Roots"]:
            with self.subTest(name=name):
                self.assertTrue(by_name[name].get("chain_branch"))
                self.assertIn("seattleroots.org", by_name[name]["chain_reason"])

    def test_independent_clinics_are_never_flagged(self):
        """The regression that would matter most.

        Pakistani hunts are the working business. Each clinic here has its own
        domain, and flagging any of them would break the market that pays.
        """
        fresh = _leads(LAHORE)
        n = _mark_chain_branches({}, fresh)
        self.assertEqual(n, 0, "independent businesses must never be flagged")
        self.assertFalse(any(l.get("chain_branch") for l in fresh))

    def test_the_same_business_seen_twice_is_not_a_chain(self):
        """A hunt runs many rounds and re-sees businesses constantly.

        Counting records rather than distinct names would flag every
        single-location business that appeared in two rounds - which is most
        of them - and empty the pipeline completely.
        """
        fresh = _leads([("Smile Hub Clinics", "https://smilehubclinics.com/a"),
                        ("smile hub clinics", "https://smilehubclinics.com/b")])
        self.assertEqual(_mark_chain_branches({}, fresh), 0,
                         "one business seen twice is not two branches")

    def test_branches_are_counted_across_rounds_not_within_one(self):
        """swedish.org appeared ONCE per round but in several rounds.

        A single round cannot see the pattern; the pool can. This is why the
        check lives in the harvester, where every business seen so far is
        still in hand, rather than inside the scraper.
        """
        pool = {"a": {"business_name": "Swedish Primary Care - Downtown",
                      "website": "https://www.swedish.org/a"}}
        fresh = _leads([("Swedish Primary Care - Ballard",
                         "https://www.swedish.org/b")])
        self.assertEqual(_mark_chain_branches(pool, fresh), 1,
                         "an earlier round's branch must still count")

    def test_a_lead_with_no_website_is_not_a_chain(self):
        """No website is a REASON to contact someone, never a rejection."""
        fresh = _leads([("Acupuncture & Wellness Center", ""),
                        ("CVS Pharmacy", ""),
                        ("Corner Clinic", "")])
        self.assertEqual(_mark_chain_branches({}, fresh), 0,
                         "an empty website must not group leads together")

    def test_domain_normalisation(self):
        for url, want in [
            ("https://www.uwmedicine.org/clinic/a", "uwmedicine.org"),
            ("http://uwmedicine.org", "uwmedicine.org"),
            ("https://UWMedicine.ORG/x?y=1", "uwmedicine.org"),
            ("https://neighborcare.org/clinics/pike-place-market", "neighborcare.org"),
            ("", ""),
        ]:
            with self.subTest(url=url):
                self.assertEqual(_site_domain({"website": url}), want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
