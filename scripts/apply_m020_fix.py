#!/usr/bin/env python3
"""
apply_m020_fix.py — bring data/regulatory/us_monograph_m020.jsonl up to date
with two FDA final orders. Idempotent: a second run changes nothing.

Verified 2026-10-08 against the orders themselves (not summaries):

1. Bemotrizinol — Final Administrative Order OTC000039
   https://www.accessdata.fda.gov/drugsatfda_docs/omuf/Order/OTC000039_Final_Administrative_Order.pdf
   Issued 2026-06-10 (corrected 2026-08-10). Takes effect 2026-08-09.
   Up to 6%, adults and children 6 months and older, finished SPF >= 2.
   Permitted: oil, lotion, cream, gel, butter, paste, ointment, stick, and
   spray only with no propellant (pump) or with the propellant isolated from
   the formulation (bag-on-valve). Not permitted: propellant-combined aerosol
   sprays, powders. Not GRASE in combination with aminobenzoic acid or
   trolamine salicylate. 18-month exclusivity for DSM Nutritional Products
   LLC from the effective date.

2. Aminobenzoic acid (PABA) and trolamine salicylate — Final Administrative
   Order OTC000008-1
   https://www.accessdata.fda.gov/drugsatfda_docs/omuf/Order/FinalAdministrativeOrderOTC000008-PABATrolamine.pdf
   Signed 2026-09-08, issued 2026-09-11 (the FDA Q&A page lists 2026-09-10).
   Removes both from M020 (risks outweigh benefits). Takes effect 2027-09-11,
   or later if disputed under FD&C Act 505G(b).
   UNTIL THAT DATE BOTH REMAIN LEGALLY IN M020. They are therefore recorded
   as a pending removal, not as removed; build_answer_keys.py turns the
   status into "removed" automatically once the effective date has passed.

Usage:  python scripts/apply_m020_fix.py [path]   (default: data/regulatory/us_monograph_m020.jsonl)
"""
import json
import os
import sys

DEFAULT = os.path.join("data", "regulatory", "us_monograph_m020.jsonl")

OTC000039_URL = ("https://www.accessdata.fda.gov/drugsatfda_docs/omuf/Order/"
                 "OTC000039_Final_Administrative_Order.pdf")
OTC000008_1_URL = ("https://www.accessdata.fda.gov/drugsatfda_docs/omuf/Order/"
                   "FinalAdministrativeOrderOTC000008-PABATrolamine.pdf")

BEMOTRIZINOL = {
    "id": "US:M020-bemotrizinol",
    "jurisdiction": "US",
    "axis": "regulatory",
    "monograph": "M020",
    "paragraph": "M020.10",
    "inci_name": "Bemotrizinol",
    "alt_names": ["Bis-Ethylhexyloxyphenol Methoxyphenyl Triazine", "BEMT"],
    "max_concentration_pct": 6.0,
    "conditions": (
        "In force since 2026-08-09 (Final Administrative Order OTC000039). "
        "GRASE up to 6% for adults and children 6 months of age and older; "
        "finished product SPF >= 2. Permitted dosage forms: oil, lotion, cream, "
        "gel, butter, paste, ointment, stick; spray only with no propellant "
        "(pump) or with the propellant isolated from the formulation "
        "(bag-on-valve). Not permitted: propellant-combined aerosol sprays, "
        "powders. Not GRASE in combination with aminobenzoic acid or trolamine "
        "salicylate. 18-month marketing exclusivity for DSM Nutritional "
        "Products LLC from the effective date."
    ),
    "note": None,
    "grase": True,
    "source": "FDA Final Administrative Order OTC000039 (issued 2026-06-10, corrected 2026-08-10)",
    "source_url": OTC000039_URL,
    "source_version": "final order; effective 2026-08-09",
    "source_status": "VERIFIED_PRIMARY",
    "verified_date": "2026-10-08",
}

PENDING_REMOVAL = {
    "type": "removal",
    "order": "Final Administrative Order OTC000008-1",
    "signed": "2026-09-08",
    "issued": "2026-09-11",
    "effective": "2027-09-11",
    "effective_note": "or later if the order is disputed under FD&C Act 505G(b)",
    "finding": "risks outweigh benefits; not GRASE",
    "source_url": OTC000008_1_URL,
    "verified_date": "2026-10-08",
}
PENDING_NOTE = ("Removal from M020 finalized by Final Administrative Order "
                "OTC000008-1 (issued 2026-09-11); takes effect 2027-09-11. "
                "Still a listed M020 active until then.")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]

    out, changes = [], []
    for r in rows:
        name = (r.get("inci_name") or "").strip().lower()
        if name == "bemotrizinol":
            if r != BEMOTRIZINOL:
                changes.append(f"bemotrizinol: {r.get('id')} -> final order row")
            r = dict(BEMOTRIZINOL)
        elif name in ("aminobenzoic acid", "trolamine salicylate"):
            new = dict(r)
            new["grase"] = True            # legally still listed until 2027-09-11
            new["pending_change"] = dict(PENDING_REMOVAL)
            new["note"] = PENDING_NOTE
            if new != r:
                changes.append(f"{name}: recorded as pending removal (effective 2027-09-11)")
            r = new
        out.append(r)

    if not any((x.get("inci_name") or "").lower() == "bemotrizinol" for x in out):
        out.append(dict(BEMOTRIZINOL))
        changes.append("bemotrizinol: row added")

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    print(f"{path}: {len(out)} rows")
    for c in changes:
        print("  " + c)
    if not changes:
        print("  already up to date")


if __name__ == "__main__":
    main()
