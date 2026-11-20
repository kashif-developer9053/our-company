"""The scraper must claim the version of the browser it is actually running.

On 2026-11-19 every hunt returned zero businesses from the VPS. Not a single
round of a 12-round Seattle hunt found anything, and the harvester reported it
the way it reports an empty market: "this niche/area looks exhausted".

The cause was two years of drift between two things nobody thought of as
related:

    _UA constant, written once          -> Chrome/125.0.0.0
    Chromium installed by the deploy    -> 151.0.7922.34

Google reads that mismatch as automation. Three probes from the VPS, same
code and same query, differing only in the user agent:

    stale UA (125), resources blocked -> FAIL, 60s timeout, 0 cards
    real  UA (151), resources blocked -> feed found, 10 cards
    real  UA (151), nothing blocked   -> feed found, 10 cards

What made this expensive to find is that it did NOT reproduce from a home
connection: a residential IP buys enough benefit of the doubt to survive a bad
user agent, so the identical code kept returning 40 businesses a round on a
developer machine while production found nothing. The failure was invisible
anywhere except the server it mattered on.

A test that asserted the UA string equalled some expected literal would have
passed throughout - the string was never wrong, it was only old. So these
tests check the RELATIONSHIP between the claim and the browser instead.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent1.scraper import _UA_FALLBACK, _ua_for  # noqa: E402


class _FakeBrowser:
    def __init__(self, version):
        self.version = version


class UserAgentFollowsTheBrowserTests(unittest.TestCase):

    def test_the_claimed_major_version_is_the_browsers_own(self):
        """The whole bug in one assertion."""
        for version, expected_major in (
            ("151.0.7922.34", "151"),
            ("149.0.7827.55", "149"),
            ("125.0.6422.60", "125"),       # if it really IS 125, say 125
            ("Chrome/151.0.7922.34", "151"),  # some channels prefix it
            ("200.1.2.3", "200"),           # future versions, no upper bound
        ):
            with self.subTest(version=version):
                ua = _ua_for(_FakeBrowser(version))
                found = re.search(r"Chrome/(\d+)\.", ua)
                self.assertIsNotNone(found, f"no Chrome version in {ua!r}")
                self.assertEqual(
                    found.group(1), expected_major,
                    f"browser is {version} but the scraper claimed {found.group(1)} "
                    f"- that mismatch is what returned zero leads for every hunt")

    def test_a_version_that_cannot_be_read_still_yields_a_usable_ua(self):
        """A missing version must not crash a hunt, or send something absurd."""
        for bad in (None, "", "unknown", "not.a.version", object()):
            with self.subTest(bad=bad):
                ua = _ua_for(_FakeBrowser(bad))
                self.assertTrue(ua.startswith("Mozilla/5.0"),
                                f"unusable user agent {ua!r}")
                self.assertIn("Chrome/", ua)

    def test_a_browser_that_raises_does_not_break_the_scraper(self):
        """browser.version is a property on a real object; it can throw."""
        class Exploding:
            @property
            def version(self):
                raise RuntimeError("browser already closed")

        self.assertEqual(_ua_for(Exploding()), _UA_FALLBACK)

    def test_no_hardcoded_user_agent_is_sent_to_the_browser_context(self):
        """Guard against the constant creeping back in.

        The fix is only durable if new_context derives the string. If someone
        re-pins a literal, this hunt silently returns zero again - and the
        symptom appears only in production, which is the worst place to
        discover it.
        """
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent1", "scraper.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()

        self.assertIn("user_agent=_ua_for(browser)", src,
                      "the Maps context must derive its UA from the browser")

        # A pinned four-part Chrome version may appear in exactly one piece of
        # running code: the documented _UA_FALLBACK. Anywhere else is drift
        # waiting to happen.
        #
        # This walks the parsed syntax tree rather than scanning lines. Two
        # earlier attempts scanned text and both failed on their own terms:
        # slicing the file into regions got its boundaries wrong and flagged
        # the fallback it meant to permit, and skipping "# ..." lines still
        # flagged the docstring that explains the outage. Comments and
        # docstrings are prose about Chrome/125; only a string that the module
        # actually evaluates can be sent to Google.
        import ast

        tree = ast.parse(src)
        fallback_strings = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", None) == "_UA_FALLBACK"
                            for t in node.targets)):
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        fallback_strings.add(id(sub))

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))

        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in fallback_strings or id(node) in docstrings:
                continue
            if re.search(r"Chrome/\d+\.\d+\.\d+\.\d+", node.value):
                offenders.append("  line %s: %r" % (node.lineno, node.value))

        self.assertEqual(
            offenders, [],
            "a Chrome version is pinned in code outside _UA_FALLBACK, so it "
            "will drift out of date exactly as Chrome/125 did:\n"
            + "\n".join(offenders))


class FallbackSanityTests(unittest.TestCase):

    def test_the_fallback_is_not_the_version_that_caused_the_outage(self):
        """125 was two years stale when it broke. Do not ship it as a default."""
        found = re.search(r"Chrome/(\d+)\.", _UA_FALLBACK)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(
            int(found.group(1)), 149,
            "the fallback must be a plausibly recent Chrome; 125 is the "
            "version Google refused")


if __name__ == "__main__":
    unittest.main(verbosity=2)
