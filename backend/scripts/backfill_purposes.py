"""Backfill `purposes` onto leads collected before purposes existed.

Leads harvested before agent1/purposes.py carry no `purposes`, so the writers
would diagnose them live on every single message. This stamps the diagnosis
once, and repairs the remarks that still name a fault we no longer collect on.

Run from the backend directory. Dry run by default; pass --apply to write.

    python scripts/backfill_purposes.py            # show what would change
    python scripts/backfill_purposes.py --apply    # write it

Safe to re-run: it only touches leads that have no purposes yet.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv('.env')

from agent1.purposes import diagnose, label, reason_line
from shared.database import get_db

APPLY = "--apply" in sys.argv

db = get_db()
L = db["leads"]

todo = list(L.find({"purposes": {"$in": [None, []]}}))
print(f"leads without purposes: {len(todo)}   (mode: {'APPLY' if APPLY else 'dry run'})\n")

counts = Counter()
none_at_all = []
ops = []
for l in todo:
    p = diagnose(l)
    counts[" + ".join(label(x) for x in p) or "(nothing sellable)"] += 1
    if not p:
        none_at_all.append(l.get("business_name"))
        continue
    update = {"purposes": p}
    # Two kinds of remark exist. The software ones ("...is the kind of business
    # where sales are recorded by hand") are already purpose-shaped and read
    # better than anything generated here, so they stay.
    #
    # The website ones are the auditor's summary, and it lists faults in the
    # order it found them — so a lead with a real HTTP 500 can still open with
    # "No HTTPS (insecure site)", the cosmetic fault we stopped collecting on.
    # A remark that LEADS with a fault we no longer act on contradicts the
    # pitch, so those are replaced.
    cur = (l.get("collection_reason") or "").strip()
    AUDIT_PREFIX = "Collected because their site has fixable problems:"
    if not cur:
        keeps = False
    elif not cur.startswith(AUDIT_PREFIX):
        keeps = True                      # existing purpose-style prose
    else:
        first = cur[len(AUDIT_PREFIX):].strip().lower()
        keeps = first.startswith(("no website", "website does not load",
                                  "site returns http"))
    if not keeps:
        update["collection_reason"] = reason_line(p, l)
    ops.append((l["_id"], update))

print("what they would be pitched:")
for k, v in counts.most_common():
    print(f"  {v:5}  {k}")

reasons_rewritten = sum(1 for _, u in ops if "collection_reason" in u)
print(f"\nwould set purposes on {len(ops)} leads; "
      f"rewrite {reasons_rewritten} empty/'no significant issues' remarks")
if none_at_all:
    print(f"nothing sellable ({len(none_at_all)}): {none_at_all[:5]}")

if APPLY:
    from pymongo import UpdateOne
    res = L.bulk_write([UpdateOne({"_id": i}, {"$set": u}) for i, u in ops])
    print(f"\nmodified {res.modified_count} leads")
