#!/usr/bin/env python3
"""
scripts/verify_same_list.py — check each "same ingredient list" pair against
the PRINTED Drug Facts text, not just the SPL structured tables.

Why: structured SPL tables can omit items the printed label lists (2026-10-08:
Equate Kids SPF 50 vs CVS Health SPF 50 had identical tables, but the CVS
Drug Facts adds "fragrance"). A pair is published only if the printed
Inactive ingredients lists match as well.

Reads  claims/same_ingredient_list_pairs.csv
Writes claims/same_list_label_check.json
Needs network access to dailymed.nlm.nih.gov (run in GitHub Actions).
"""
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_strengths import fetch_xml, panel_percents  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(ROOT, "claims", "same_ingredient_list_pairs.csv")
OUT = os.path.join(ROOT, "claims", "same_list_label_check.json")

# Drug Facts "Inactive ingredients" (LOINC 51727-6) or a section titled so.
INACTIVE_SECTION = re.compile(
    r"<section\b[^>]*>(?:(?!</section>).)*?(?:51727-6|Inactive\s+ingredient)"
    r"((?:(?!</section>).)*)</section>", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")


def norm_item(s):
    """Case, spacing and punctuation only. Text in parentheses is KEPT, so
    'extract (calendula)' and 'extract (chamomile)' stay different."""
    s = s.upper().replace("(", " ( ").replace(")", " ) ")
    s = re.sub(r"[^A-Z0-9/()\- ]", " ", s)
    s = re.sub(r"\s*([/\-])\s*", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def printed_inactives(xml):
    if not xml:
        return None
    best = None
    for m in INACTIVE_SECTION.finditer(xml):
        text = re.sub(r"\s+", " ", TAG.sub(" ", m.group(1))).strip()
        text = re.sub(r"^.*?inactive\s+ingredients?\s*[:\-]?\s*", "", text, flags=re.I)
        items = [norm_item(x) for x in re.split(r"[,;•·]|\s\*\s", text)]
        items = [x for x in items if x and len(x) < 80]
        if items and (best is None or len(items) > len(best)):
            best = items
    return best


def label(setid):
    xml = fetch_xml(setid)
    time.sleep(0.4)
    return {"inactives": printed_inactives(xml), "actives": panel_percents(xml), "fetched": xml is not None}


def main():
    rows = list(csv.DictReader(open(PAIRS, encoding="utf-8")))
    sid = lambda u: u.rsplit("setid=", 1)[-1]
    ids = sorted({sid(r["baby_kids_dailymed"]) for r in rows} | {sid(r["same_list_dailymed"]) for r in rows})
    with ThreadPoolExecutor(4) as ex:
        labels = dict(zip(ids, ex.map(label, ids)))
    out = []
    for r in rows:
        a, b = labels[sid(r["baby_kids_dailymed"])], labels[sid(r["same_list_dailymed"])]
        ia, ib = a["inactives"], b["inactives"]
        if not (a["fetched"] and b["fetched"]) or not ia or not ib:
            verdict, diff = "unreadable", None
        else:
            sa, sb = set(ia), set(ib)
            same_actives = a["actives"] == b["actives"] and bool(a["actives"])
            verdict = "match" if (ia == ib and same_actives) else "differs"
            diff = {"only_baby": sorted(sa - sb), "only_other": sorted(sb - sa),
                    "actives_baby": a["actives"], "actives_other": b["actives"],
                    "same_order": ia == ib}
        out.append({"baby": r["baby_kids_dailymed"], "other": r["same_list_dailymed"],
                    "baby_title": r["baby_kids_title"], "other_title": r["same_list_title"],
                    "verdict": verdict, "diff": diff})
    json.dump({"checked": time.strftime("%Y-%m-%d"), "pairs": out}, open(OUT, "w"), indent=1, ensure_ascii=False)
    c = {}
    for o in out:
        c[o["verdict"]] = c.get(o["verdict"], 0) + 1
    print("printed-label check:", c)


if __name__ == "__main__":
    main()
