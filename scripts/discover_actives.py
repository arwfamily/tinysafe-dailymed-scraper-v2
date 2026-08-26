#!/usr/bin/env python3
"""
discover_actives.py — find the filters our net does not know about.

The net is a whitelist of UNII seeds, so anything outside it is invisible, and
you cannot search for a name you have never heard. Two ways round that, and
this script does both.

  PASS 1 — CO-OCCURRENCE (free, automatic, no guessing)
    Every SPL we collected carries its FULL active-ingredient list. When a
    product pairs a known filter with an active we have no seed for, that
    active is a filter candidate — and it arrives with its own UNII attached,
    straight from the SPL. No name to guess, no code to invent.
    Blind spot: a filter never co-formulated with anything we already track.

  PASS 2 — ENUMERATION PROBE (paid in API calls, but it MEASURES the blind spot)
    Pages /spls?marketing_category_code=C200263 (OTC Monograph Drug) and counts
    the titles that look like sunscreen. Compare that to what we collected and
    the miss is a number rather than a worry. C200263 covers every OTC monograph
    drug — antacids, cough syrup, sunscreen — so the sunscreen judgement is made
    locally on the title.

Writes:
  data/reference/discovered_actives.json   ranked candidates + coverage figures

Nothing here edits the seed file. Promotion is a decision, not a side effect:
add the name to UV_FILTERS in resolve_uniis.py and the next run resolves it.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
SEED_FILE = "data/reference/uv_filter_uniis.json"
OUT = "data/reference/discovered_actives.json"
OTC_MONOGRAPH = "C200263"          # FDA Marketing Category: OTC Monograph Drug

SUNSCREEN_TITLE = re.compile(r"\bSUNSCREEN\b|\bSUNBLOCK\b|\bSPF\s*\d", re.I)

# Actives that legitimately appear alongside a UV filter without being one.
# Recorded, then set aside, so the candidate list stays readable.
NOT_A_FILTER = [
    "DIMETHICONE", "PETROLATUM", "WHITE PETROLATUM", "LANOLIN", "GLYCERIN",
    "COD LIVER OIL", "ALLANTOIN", "CALAMINE", "COLLOIDAL OATMEAL",
    "MENTHOL", "CAMPHOR", "PRAMOXINE", "HYDROCORTISONE", "BENZALKONIUM",
    "SALICYLIC ACID", "BENZOYL PEROXIDE", "SULFUR", "UREA", "KAOLIN",
    "MINERAL OIL", "CORN STARCH", "ALUMINUM", "MAGNESIUM", "TALC",
    "OCTINOXATE ",  # trailing space guard: never blocks the real name
]


def norm(s):
    s = str(s or "").upper()
    s = re.sub(r"\.(ALPHA|BETA|GAMMA|DELTA|DL|D|L)\.-?", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def looks_like_filter(name):
    n = norm(name)
    return not any(b.strip() and b.strip() in n for b in NOT_A_FILTER)


def fetch(url, tries=3, backoff=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "TinySafe-research/2.2 (contact: support@tinysafe.app)",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                print(f"    fetch failed: {e}", file=sys.stderr)
                return None
            time.sleep(backoff * (i + 1))
    return None


def load_seeds():
    try:
        doc = json.load(open(SEED_FILE, encoding="utf-8"))
    except Exception:
        return set(), {}
    codes, names = set(), {}
    for row in doc.get("filters", []):
        if row.get("unii"):
            codes.add(row["unii"])
            names[row["unii"]] = row.get("query")
    return codes, names


# ------------------------------------------------------------ pass 1
def co_occurrence(products, seed_codes):
    """Actives that share a product with a seeded filter but are not seeded."""
    cand = defaultdict(lambda: {"unii": None, "names": Counter(),
                                "products": 0, "example_setids": [],
                                "co_occurs_with": Counter()})
    seen_no_unii = Counter()

    for p in products:
        acts = p.get("active_ingredients") or []
        codes = []
        for a in acts:
            u = (a.get("unii") or "").strip().upper() if isinstance(a, dict) else ""
            codes.append(u)
        if not any(c in seed_codes for c in codes if c):
            continue                      # not anchored to a known filter
        anchors = [c for c in codes if c in seed_codes]
        for a in acts:
            if not isinstance(a, dict):
                continue
            u = (a.get("unii") or "").strip().upper()
            nm = a.get("name") or ""
            if u and u in seed_codes:
                continue
            if not looks_like_filter(nm):
                continue
            if not u:
                seen_no_unii[norm(nm)] += 1
                continue
            e = cand[u]
            e["unii"] = u
            e["names"][nm] += 1
            e["products"] += 1
            if len(e["example_setids"]) < 5:
                e["example_setids"].append(p.get("setid"))
            for anc in anchors:
                e["co_occurs_with"][anc] += 1

    out = []
    for u, e in cand.items():
        out.append({
            "unii": u,
            "name": e["names"].most_common(1)[0][0],
            "name_variants": [n for n, _ in e["names"].most_common(5)],
            "product_count": e["products"],
            "co_occurs_with_seeds": dict(e["co_occurs_with"]),
            "example_setids": e["example_setids"],
        })
    out.sort(key=lambda x: -x["product_count"])
    return out, seen_no_unii


# ------------------------------------------------------------ pass 2
def enumeration_probe(max_pages, collected_setids):
    """Count sunscreen-looking SPLs in the whole OTC monograph category."""
    page, scanned, sunscreenish, missed = 1, 0, 0, []
    total_elements = None
    while page <= max_pages:
        doc = fetch(f"{BASE}/spls.json?marketing_category_code={OTC_MONOGRAPH}"
                    f"&pagesize=100&page={page}")
        if doc is None:
            print(f"  probe stopped at page {page}", file=sys.stderr)
            break
        meta = doc.get("metadata", {})
        if total_elements is None:
            total_elements = meta.get("total_elements")
            print(f"  category {OTC_MONOGRAPH}: total_elements={total_elements} "
                  f"total_pages={meta.get('total_pages')}", flush=True)
        batch = doc.get("data") or []
        if not batch:
            break
        for row in batch:
            scanned += 1
            title = row.get("title") or ""
            if SUNSCREEN_TITLE.search(title):
                sunscreenish += 1
                sid = row.get("setid")
                if sid and sid not in collected_setids:
                    if len(missed) < 500:
                        missed.append({"setid": sid, "title": title[:180]})
        if not meta.get("next_page"):
            break
        page += 1
        if page % 25 == 0:
            print(f"  ...page {page} scanned={scanned} sunscreen={sunscreenish} "
                  f"missed={len(missed)}", flush=True)
        time.sleep(0.15)
    return {
        "category_total_elements": total_elements,
        "pages_scanned": page,
        "spls_scanned": scanned,
        "sunscreen_titles": sunscreenish,
        "not_in_our_corpus": len(missed),
        "complete": page <= max_pages,
        "examples": missed[:60],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="output/tinysafe_dailymed_v2_master.json")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--probe", action="store_true",
                    help="also run the enumeration probe (slow, many API calls)")
    ap.add_argument("--probe-max-pages", type=int, default=400)
    args = ap.parse_args()

    if not os.path.exists(args.master):
        print(f"FATAL: {args.master} not found", file=sys.stderr)
        return 1
    doc = json.load(open(args.master, encoding="utf-8"))
    products = doc.get("products", [])
    seed_codes, seed_names = load_seeds()
    print(f"[input] {len(products)} products, {len(seed_codes)} seeded UNIIs",
          flush=True)

    cands, no_unii = co_occurrence(products, seed_codes)

    print("\n--- PASS 1: CO-OCCURRENCE ---")
    if not cands:
        print("  no unseeded actives found alongside a known filter.")
    for c in cands[:25]:
        partners = ", ".join(seed_names.get(k, k) for k in c["co_occurs_with_seeds"])
        print(f"  {c['product_count']:5}x  {c['unii']:12} {c['name'][:44]:44} "
              f"| with: {partners[:40]}")
    if len(cands) > 25:
        print(f"  ... {len(cands) - 25} more in {args.out}")
    if no_unii:
        print(f"\n  {len(no_unii)} unseeded actives had NO UNII in the SPL "
              f"(cannot be seeded): {', '.join(list(no_unii)[:6])}")

    result = {
        "built_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "products_examined": len(products),
        "seeded_uniis": len(seed_codes),
        "how_to_promote": "add the NAME to UV_FILTERS in scripts/resolve_uniis.py; "
                          "the next run resolves it from DailyMed. Never paste the "
                          "UNII by hand — let the resolver confirm it.",
        "candidates": cands,
        "unseeded_actives_without_unii": dict(no_unii.most_common(50)),
    }

    if args.probe:
        print("\n--- PASS 2: ENUMERATION PROBE ---")
        collected = {p.get("setid") for p in products}
        result["enumeration_probe"] = enumeration_probe(args.probe_max_pages, collected)
        pr = result["enumeration_probe"]
        print(f"  sunscreen-titled SPLs in category : {pr['sunscreen_titles']}")
        print(f"  of those, not in our corpus       : {pr['not_in_our_corpus']}")
        if not pr["complete"]:
            print("  !! probe hit the page cap — the miss count is a LOWER BOUND")
        if pr["sunscreen_titles"]:
            cov = 100 * (pr["sunscreen_titles"] - pr["not_in_our_corpus"]) / pr["sunscreen_titles"]
            print(f"  title-based coverage estimate     : {cov:.1f}%")
            result["enumeration_probe"]["coverage_estimate_percent"] = round(cov, 1)
    else:
        print("\n--- PASS 2 skipped (use --probe to measure the blind spot) ---")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
