"""Re-label leads whose "broken website" was really a bot block.

The auditor treated any HTTP status >= 400 as a critical site defect. Several
of those codes mean the opposite: the site is healthy and simply refused our
checker. 403 (WAF/bot block) and 429 (rate limited) accounted for 107 of the
140 leads flagged with a broken site — including businesses whose sites open
perfectly in a browser.

Those leads were collected for a reason that is not true, and outreach would
have told the owner their working site was broken. This rewrites the finding,
the headline, the summary and the collection reason, and drops the audit's
`qualified` flag so the lead is judged on the business instead.

Leads whose only reason to exist was that false fault are flagged for review
rather than deleted — the business may still be a fine prospect for something
else, and that is the CEO's call, not a script's.

Idempotent: safe to run more than once.

    python scripts/fix_bot_blocked_audits.py --dry-run
    python scripts/fix_bot_blocked_audits.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from agent1.site_auditor import _BOT_BLOCK_CODES, build_reason  # noqa: E402
from shared.database import get_db  # noqa: E402

_CODE_RE = re.compile(r"responded\s+(\d{3})")


def _blocked_code(finding: dict) -> int | None:
    """The bot-block status this finding reports, if that is what it is."""
    if finding.get("code") != "http_error":
        return None
    m = _CODE_RE.search(finding.get("evidence", "") or "")
    if not m:
        return None
    code = int(m.group(1))
    return code if code in _BOT_BLOCK_CODES else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write nothing")
    ap.add_argument("--no-flag", action="store_true",
                    help="correct the wrong reasons but leave lead statuses "
                         "alone (do not mark any lead needs_review)")
    args = ap.parse_args()

    col = get_db()["leads"]
    changed = flagged = 0

    for lead in col.find({"site_audit.findings.code": "http_error"}):
        audit = lead.get("site_audit") or {}
        findings = audit.get("findings") or []

        code = next((c for c in (_blocked_code(f) for f in findings) if c), None)
        if code is None:
            continue  # a real 404/500 — leave it alone

        url = lead.get("website") or ""
        rebuilt = [f for f in findings if _blocked_code(f) is None]
        rebuilt.insert(0, {
            "code": "blocked_to_us",
            "severity": "low",
            "title": "Could not check the site automatically",
            "evidence": (f"{url} responded {code} to our checker "
                         f"(bot protection or rate limiting) — the site "
                         f"itself looks fine"),
            "pitch": "No pitch here: we could not see the site, so we know "
                     "nothing about it.",
        })

        audit["findings"] = rebuilt
        audit["unknown"] = True
        audit["qualified"] = False
        audit["headline"] = "Could not check the site automatically"
        audit["summary"] = build_reason(audit)

        update: dict = {"site_audit": audit}

        # The stated reason was the false fault, so replace it.
        reason = (lead.get("collection_reason") or "")
        if "HTTP" in reason or "fixable problems" in reason:
            update["collection_reason"] = audit["summary"]

        # If the broken site was the ONLY thing we had on them, this lead has
        # no honest reason to be in the CRM any more. Flag, never delete.
        purposes = [p for p in (lead.get("purposes") or []) if p != "website"]
        if (not args.no_flag and not purposes
                and lead.get("status") not in ("rejected", "needs_review")):
            update["needs_review"] = True
            update["review_note"] = (
                "Collected because their website looked broken, but it was "
                "only blocking our checker. Re-check whether we can sell "
                "them anything.")
            flagged += 1

        changed += 1
        if args.dry_run:
            # Business names carry Urdu and accented characters; a Windows
            # console in cp1252 cannot encode them and would crash the run.
            name = (lead.get("business_name") or "?")[:38]
            safe = name.encode(sys.stdout.encoding or "utf-8",
                               "replace").decode(sys.stdout.encoding or "utf-8")
            print(f"  would fix  {safe:38} HTTP {code}  {url[:40]}")
        else:
            col.update_one({"id": lead["id"]}, {"$set": update})

    verb = "Would update" if args.dry_run else "Updated"
    print(f"\n{verb} {changed} lead(s) mislabelled as having a broken site.")
    print(f"{'Would flag' if args.dry_run else 'Flagged'} {flagged} for review "
          f"(no other reason to keep them).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
