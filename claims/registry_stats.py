#!/usr/bin/env python3
"""
claims/registry_stats.py — compute the registry measurements for the evidence
pages and write them into claims/claim_ledger.json as verified claims.

Population (owner decision 2026-10-08, "strict"):
  products whose LABEL says baby or kids (claims/baby_review_*.csv,
  decision == include), product_type sunscreen or reviewed-in zinc product,
  counted once per unique formulation (formulation_hash).

Every number here is recomputed from two files in this repo; nothing is typed
by hand. Run after any data refresh:
  python claims/registry_stats.py
"""
import csv
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical", "us_sunscreens.jsonl")
LEDGER = os.path.join(ROOT, "claims", "claim_ledger.json")
REPO_URL = "https://github.com/arwfamily/tinysafe-dailymed-scraper-v2/blob/main"

FILTERS = [  # slug, display name, classifier canonical name
    ("zinc-oxide", "zinc oxide", "zinc oxide"),
    ("titanium-dioxide", "titanium dioxide", "titanium dioxide"),
    ("bemotrizinol", "bemotrizinol", "bemotrizinol"),
    ("avobenzone", "avobenzone", "avobenzone"),
    ("oxybenzone", "oxybenzone", "oxybenzone"),
    ("octinoxate", "octinoxate", "octinoxate"),
    ("homosalate", "homosalate", "homosalate"),
    ("octisalate", "octisalate", "octisalate"),
    ("octocrylene", "octocrylene", "octocrylene"),
    ("ensulizole", "ensulizole", "ensulizole"),
    ("meradimate", "meradimate", "meradimate"),
    ("dioxybenzone", "dioxybenzone", "dioxybenzone"),
    ("sulisobenzone", "sulisobenzone", "sulisobenzone"),
    ("cinoxate", "cinoxate", "cinoxate"),
    ("padimate-o", "padimate O", "padimate O"),
    ("paba", "PABA (aminobenzoic acid)", "aminobenzoic acid"),
    ("trolamine-salicylate", "trolamine salicylate", "trolamine salicylate"),
    ("ecamsule", "ecamsule", "ecamsule"),
    ("drometrizole-trisiloxane", "drometrizole trisiloxane", "drometrizole trisiloxane"),
    ("ethylhexyl-triazone", "ethylhexyl triazone", "ethylhexyl triazone"),
]


def load():
    review = sorted(glob.glob(os.path.join(ROOT, "claims", "baby_review_*.csv")))[-1]
    with open(review, encoding="utf-8") as f:
        include = {r["setid"] for r in csv.DictReader(f) if r["decision"] == "include"}
    recs = [json.loads(l) for l in open(CANON, encoding="utf-8") if l.strip()]
    snapshot = max(r.get("last_seen") or "" for r in recs)
    baby = [r for r in recs if r["setid"] in include]
    uniq = {}
    for r in sorted(baby, key=lambda r: r["setid"]):
        uniq.setdefault(r["formulation_hash"], r)
    return review, snapshot, list(uniq.values())


def source(review, snapshot):
    return {"title": "FDA DailyMed SPL registry (structured product labels), ARW House analysis",
            "url": f"{REPO_URL}/data/canonical/us_sunscreens.jsonl",
            "list_url": f"{REPO_URL}/claims/{os.path.basename(review)}",
            "method_url": f"{REPO_URL}/claims/registry_stats.py",
            "snapshot": snapshot}


POP = ("unique formulations of sunscreen labels that say baby or kids "
       "(FDA DailyMed; selected by rule from the label, with edge cases decided by hand "
       "and every decision recorded with its reason)")
POP_MIN = POP + "; mineral-only actives (zinc oxide and/or titanium dioxide)"
CAVEAT = ("DailyMed lists drug labels submitted to the FDA, including labels for products "
          "made in US facilities for other markets. A listing is not proof that a product "
          "is on US shelves today.")


def main():
    review, snapshot, forms = load()
    src = source(review, snapshot)
    N = len(forms)
    claims = []
    for slug, name, canon in FILTERS:
        n = sum(1 for r in forms
                if canon in (r.get("uv_filters_mineral") or []) + (r.get("uv_filters_organic") or []))
        lead = "None" if n == 0 else str(n)
        claims.append({
            "id": f"US-BABY-ACTIVE-{slug}", "status": "verified", "jurisdiction": "US",
            "ingredient_slugs": [slug],
            "claim": f"{n} of {N} baby/kids sunscreen formulations list {name} as an active ingredient.",
            "publishable_sentence": (f"{lead} of the {N} baby and kids sunscreen formulas listed "
                                     f"in the FDA's DailyMed label database name {name} as an active ingredient."),
            "numerator": n, "denominator": N, "population": POP,
            "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot})
    mineral = [r for r in forms if r.get("is_mineral_only_actives")]
    M = len(mineral)
    zno = sum(1 for r in mineral if r.get("contains_zinc_oxide"))
    hidden = sum(1 for r in mineral if r.get("uv_absorbers_in_inactives"))
    bos = sum(1 for r in mineral if any(a["canonical"] == "butyloctyl salicylate"
                                        for a in r.get("uv_absorbers_in_inactives") or []))
    claims += [
        {"id": "US-BABY-MINERAL-ZNO", "status": "verified", "jurisdiction": "US",
         "ingredient_slugs": ["zinc-oxide"],
         "claim": f"{zno} of {M} mineral-only baby/kids sunscreen formulations contain zinc oxide.",
         "publishable_sentence": (f"{zno} of the {M} mineral baby and kids sunscreen formulas "
                                  f"listed in the FDA's DailyMed label database contain zinc oxide."),
         "numerator": zno, "denominator": M, "population": POP_MIN,
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot},
        {"id": "US-BABY-HIDDEN-UV", "status": "provisional_do_not_publish", "jurisdiction": "US",
         "blocker": ("The count is exact, but 'absorbs UV light' is not supported for the two "
                     "largest ingredients: the butyloctyl salicylate manufacturer (Hallstar) describes "
                     "SPF contribution and UV-filter stabilisation, not UV absorption; DrugBank "
                     "DB11226 describes ethylhexyl methoxycrylene as a photostabilizer that works "
                     "without absorbing sunlight. Each of the 7 ingredients needs its own sourced "
                     "function before a combined sentence can be published."),
         "ingredient_slugs": [], "finding": "hidden-uv-absorbers",
         "claim": (f"{hidden} of {M} mineral-only baby/kids sunscreen formulations contain at least "
                   f"one UV-absorbing ingredient that is not listed as an active ingredient."),
         "publishable_sentence": (f"{hidden} of the {M} mineral baby and kids sunscreen formulas "
                                  f"listed in the FDA's DailyMed label database also contain an ingredient that absorbs "
                                  f"UV light but is not listed as an active ingredient."),
         "legal_framing": ("Not a violation: these ingredients are not FDA sunscreen actives, so "
                           "listing them as actives would itself be non-compliant. The finding is "
                           "about how labels work, not about any brand."),
         "numerator": hidden, "denominator": M, "population": POP_MIN,
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py + scripts/classify.py (two-tier absorber list)",
         "verified_date": snapshot},
        {"id": "US-BABY-BOS", "status": "verified", "jurisdiction": "US",
         "ingredient_slugs": [], "finding": "butyloctyl-salicylate",
         "claim": f"{bos} of {M} mineral-only baby/kids sunscreen formulations contain butyloctyl salicylate.",
         "publishable_sentence": (f"{bos} of the {M} mineral baby and kids sunscreen formulas "
                                  f"listed in the FDA's DailyMed label database contain butyloctyl salicylate. It is not "
                                  f"an FDA sunscreen active ingredient; its manufacturer says it can contribute to SPF "
                                  f"(no more than 2 SPF units at 5%) and help prevent some UV filters from breaking down."),
         "ingredient_source": {"title": "Butyloctyl Salicylate Q&A — Hallstar Beauty (manufacturer)",
                               "url": "https://www.hallstarbeauty.com/butyloctyl-salicylate-qa/",
                               "checked": "2026-10-08"},
         "legal_framing": ("Not a violation: butyloctyl salicylate is not an FDA sunscreen active, so it "
                           "belongs with the inactive ingredients, as the rules require. The finding is "
                           "about how labels work, not about any brand."),
         "numerator": bos, "denominator": M, "population": POP_MIN,
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot},
    ]

    with open(LEDGER, encoding="utf-8") as f:
        ledger = json.load(f)
    ids = {c["id"] for c in claims}
    kept = [c for c in ledger["claims"] if c["id"] not in ids]
    # The morning's provisional counts are superseded by the reviewed list.
    for c in kept:
        if c["id"] in ("US-HID-001", "US-HID-002"):
            c["status"] = "superseded"
            c["superseded_by"] = "US-BABY-HIDDEN-UV" if c["id"] == "US-HID-001" else "US-BABY-BOS"
    ledger["claims"] = kept + claims
    ledger["registry_population"] = {"definition": POP, "formulations": N, "mineral_only": M,
                                     "review_file": os.path.basename(review), "snapshot": snapshot}
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    print(f"population: {N} formulations ({M} mineral-only), snapshot {snapshot}")
    for c in claims:
        print(f"  {c['id']:34s} {c['numerator']:>4}/{c['denominator']}")


if __name__ == "__main__":
    main()
