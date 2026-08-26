#!/usr/bin/env python3
"""
verify_strengths.py — check every computed concentration against the label text.

WHY THIS EXISTS
  The ratio fields in an SPL (216 mg in 1 mL) and the Drug Facts panel
  ("Active ingredient: Zinc Oxide (21.6%)") are two independent statements of
  the same fact, written by the same filer in two different places. One is
  machine data, the other is the legally required consumer panel under
  21 CFR 201.66. Agreement between them is real verification; agreement between
  a rule and itself is not.

  Before this script, the unit-conversion rules were checked against 439 of
  11,189 actives (3.9%) using percentages that happened to appear in the SPL
  title. The Drug Facts panel is present on EVERY OTC label, so the same check
  can cover the whole corpus.

WHAT IT DOES
  For each setid: fetch the SPL XML, pull the "Active ingredient(s)" section,
  read the percentages printed there, and compare them to percent_ww.

  Verdicts per active:
    verified      panel and computed value agree within tolerance
    MISMATCH      both present and they disagree  <- the finding that matters
    no_panel_pct  the panel does not state a percentage for this ingredient
    unresolved    percent_ww was never computed

OUTPUT
  data/reference/strength_verification.json   per-rule accuracy + every mismatch

READ THE PER-RULE TABLE, NOT THE HEADLINE NUMBER. A rule at 100% over 4,000
actives is trustworthy; the same rule at 100% over 12 is not yet evidence.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
OUT = "data/reference/strength_verification.json"

# The Drug Facts "Active ingredient" section. LOINC 55106-9 is the standard
# code, but OTC filers also place actives in an unclassified section, so the
# text heading is matched as well.
ACTIVE_SECTION = re.compile(
    r"<(?:component|section)\b[^>]*>(?:(?!</section>).)*?"
    r"(?:55106-9|Active\s+ingredient)"
    r"((?:(?!</section>).)*)</section>",
    re.IGNORECASE | re.DOTALL)

TAG = re.compile(r"<[^>]+>")
# "Zinc Oxide (21.6%)"  /  "Zinc Oxide 21.6%"  /  "Zinc Oxide.....21.6 %"
NAME_PCT = re.compile(
    r"([A-Za-z][A-Za-z0-9 ,'\-/]{2,44}?)\s*[\(\.\:\s]*\s*([\d]+(?:\.[\d]+)?)\s*%",
    re.IGNORECASE)


def norm(s):
    s = str(s or "").upper()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_xml(setid, tries=3):
    url = f"{BASE}/spls/{setid}.xml"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def panel_percents(xml):
    """{normalised ingredient name: percent} as printed in Drug Facts."""
    if not xml:
        return {}
    out = {}
    for m in ACTIVE_SECTION.finditer(xml):
        text = TAG.sub(" ", m.group(1))
        text = re.sub(r"\s+", " ", text)
        for nm, pct in NAME_PCT.findall(text):
            key = norm(nm)
            # strip leading label words the panel puts before the name
            key = re.sub(r"^(ACTIVE INGREDIENTS?|INGREDIENT|PURPOSE)\s+", "", key)
            if len(key) < 3:
                continue
            try:
                v = float(pct)
            except ValueError:
                continue
            if 0 < v <= 100:
                out.setdefault(key, v)
    return out


def match_name(target, panel):
    t = norm(target)
    if not t:
        return None
    if t in panel:
        return panel[t]
    for k, v in panel.items():
        if t in k or k in t:
            return v
    return None


def check_one(prod, tol=0.05):
    xml = fetch_xml(prod.get("setid"))
    panel = panel_percents(xml)
    rows = []
    for a in (prod.get("active_ingredients") or []):
        basis = a.get("percent_basis")
        pct = a.get("percent_ww")
        stated = match_name(a.get("name"), panel)
        if pct is None:
            verdict = "unresolved"
        elif stated is None:
            verdict = "no_panel_pct"
        elif abs(stated - pct) / max(stated, 1e-9) <= tol:
            verdict = "verified"
        else:
            verdict = "MISMATCH"
        rows.append({
            "setid": prod.get("setid"),
            "title": (prod.get("title") or "")[:90],
            "ingredient": a.get("name"),
            "computed": pct,
            "panel_states": stated,
            "basis": basis,
            "raw": f"{a.get('strength')}{a.get('strength_unit')}"
                   f"/{a.get('denominator')}{a.get('denominator_unit')}",
            "verdict": verdict,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", default="data/canonical/us_sunscreens.jsonl")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--category", default="sunscreen",
                    help="restrict to one category, or 'all'")
    ap.add_argument("--limit", type=int, default=0, help="0 = every product")
    ap.add_argument("--parallel", type=int, default=6)
    args = ap.parse_args()

    prods = [json.loads(l) for l in open(args.canonical, encoding="utf-8") if l.strip()]
    if args.category != "all":
        prods = [p for p in prods if p.get("category") == args.category]
    if args.limit:
        prods = prods[:args.limit]
    print(f"[verify] {len(prods)} products", flush=True)

    workers = min(max(args.parallel, 1), 12)
    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(check_one, p): p for p in prods}
        for f in as_completed(futs):
            try:
                rows.extend(f.result())
            except Exception as e:
                print(f"  error: {e}", file=sys.stderr)
            done += 1
            if done % 250 == 0:
                print(f"  ...{done}/{len(prods)}", flush=True)

    by_basis = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_basis[r["basis"]][r["verdict"]] += 1

    print("\n--- PER-RULE ACCURACY (Drug Facts panel as the witness) ---")
    print(f"{'rule (percent_basis)':38}{'checked':>9}{'verified':>10}{'MISMATCH':>10}{'accuracy':>10}")
    summary = {}
    for basis, v in sorted(by_basis.items(),
                           key=lambda x: -(x[1]['verified'] + x[1]['MISMATCH'])):
        checked = v["verified"] + v["MISMATCH"]
        acc = 100.0 * v["verified"] / checked if checked else None
        summary[str(basis)] = {"checked": checked, "verified": v["verified"],
                               "mismatch": v["MISMATCH"],
                               "no_panel_pct": v["no_panel_pct"],
                               "unresolved": v["unresolved"],
                               "accuracy_percent": round(acc, 1) if acc is not None else None}
        acc_s = f"{acc:8.1f}%" if acc is not None else "       -"
        print(f"{str(basis)[:38]:38}{checked:9}{v['verified']:10}{v['MISMATCH']:10}{acc_s}")

    mism = [r for r in rows if r["verdict"] == "MISMATCH"]
    tot_checked = sum(s["checked"] for s in summary.values())
    tot_ver = sum(s["verified"] for s in summary.values())
    print(f"\ntotal checked : {tot_checked}")
    print(f"verified      : {tot_ver} "
          f"({100.0*tot_ver/tot_checked:.1f}%)" if tot_checked else "")
    print(f"MISMATCH      : {len(mism)}")
    print(f"no panel %    : {sum(s['no_panel_pct'] for s in summary.values())}")
    print(f"unresolved    : {sum(s['unresolved'] for s in summary.values())}")

    if mism:
        print("\n--- MISMATCHES (first 15) ---")
        for r in mism[:15]:
            print(f"  {r['ingredient'][:22]:22} computed {r['computed']} "
                  f"vs panel {r['panel_states']}  [{r['basis']}] {r['raw']}")
            print(f"      {r['title'][:76]}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"checked_on": time.strftime("%Y-%m-%d"),
                   "products": len(prods),
                   "witness": "Drug Facts 'Active ingredient' panel (21 CFR 201.66)",
                   "tolerance_relative": 0.05,
                   "per_rule": summary,
                   "mismatches": mism}, f, ensure_ascii=False, indent=1)
    print(f"\nwritten: {args.out}")

    # A rule that disagrees with the label more than 2% of the time is not a
    # rule, it is a guess with good luck. Fail loudly rather than let a bad
    # conversion reach a published figure.
    bad = [b for b, s in summary.items()
           if s["checked"] >= 50 and (s["accuracy_percent"] or 0) < 98]
    if bad:
        print("\n!! RULES BELOW 98% — do not publish figures derived from these:")
        for b in bad:
            print(f"   {b}: {summary[b]['accuracy_percent']}% "
                  f"over {summary[b]['checked']} checks")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
