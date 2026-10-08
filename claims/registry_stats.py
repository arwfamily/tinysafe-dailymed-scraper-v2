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
import collections
import csv
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical", "us_sunscreens.jsonl")
LEDGER = os.path.join(ROOT, "claims", "claim_ledger.json")
CORRECTIONS = os.path.join(ROOT, "data", "corrections", "spl_label_errors.jsonl")
# The 12 actives the FDA has proposed are not GRASE because more data are needed
# (FDA Q&A, content current as of 2026-09-10). Classifier canonical names.
FDA_MORE_DATA = ["avobenzone", "oxybenzone", "octinoxate", "homosalate", "octisalate", "octocrylene",
                 "ensulizole", "meradimate", "dioxybenzone", "sulisobenzone", "cinoxate", "padimate O"]
FDA_QA = {"title": "FDA — Questions and Answers: FDA's regulatory actions on over-the-counter sunscreen",
          "url": "https://www.fda.gov/drugs/understanding-over-counter-medicines/questions-and-answers-fdas-regulatory-actions-over-counter-sunscreen",
          "checked": "2026-10-08"}
EU_HOMOSALATE = {"title": "EU Cosmetics Regulation Annex VI entry 3 (homosalate), as amended by Regulation (EU) 2022/2195",
                 "url": "https://webgate.ec.europa.eu/reqs2/public/v2/requirement/auxi/eu/32009R1223_spcosmet_annex_6.pdf",
                 "checked": "2026-10-08"}
US_MAX = {"avobenzone": 3, "oxybenzone": 6, "octinoxate": 7.5, "homosalate": 15, "octisalate": 5, "octocrylene": 10,
          "ensulizole": 4, "zinc oxide": 25, "titanium dioxide": 25}
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
    # Labels whose SPL structured data contradicts their own Drug Facts text.
    # Each correction carries its evidence; see data/corrections/.
    fixes = {}
    if os.path.exists(CORRECTIONS):
        for l in open(CORRECTIONS, encoding="utf-8"):
            if l.strip():
                c = json.loads(l)
                fixes[c["setid"]] = c
    for r in recs:
        if r["setid"] in fixes:
            r.update(fixes[r["setid"]]["use"])
            r["_corrected"] = True
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
    def pct(r, word):
        for a in r.get("active_ingredients") or []:
            if word in (a.get("name") or "").upper():
                return a.get("percent_ww")
        return None

    def suspect(r):
        """Structured data with an active above its US legal maximum is a coding
        error or a foreign-market label; never use its percentages."""
        return any((pct(r, n.upper()) or 0) > mx + 0.01 for n, mx in US_MAX.items())

    orgs = lambda r: set(r.get("uv_filters_organic") or [])
    more_data = [r for r in forms if orgs(r) & set(FDA_MORE_DATA)]
    four_plus = sum(1 for r in more_data if len(orgs(r) & set(FDA_MORE_DATA)) >= 4)
    homo = [r for r in forms if "homosalate" in orgs(r)]
    homo_ok = [r for r in homo if not suspect(r) and pct(r, "HOMOSALATE") is not None]
    homo_eu = sum(1 for r in homo_ok if pct(r, "HOMOSALATE") > 7.34)
    by_percent = [[k, v] for k, v in sorted(collections.Counter(f"{pct(r, 'HOMOSALATE'):g}" for r in homo_ok).items(),
                                           key=lambda kv: -float(kv[0]))]
    claims += [
        {"id": "US-BABY-FDA-MORE-DATA", "status": "verified", "jurisdiction": "US",
         "ingredient_slugs": [], "finding": "fda-more-data",
         "claim": f"{len(more_data)} of {N} baby/kids sunscreen formulations contain at least one of the 12 actives the FDA has asked for more data on.",
         "publishable_sentence": (f"{len(more_data)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                  f"label database contain at least one of the 12 active ingredients the FDA says it needs more "
                                  f"safety data on. {four_plus} of them contain four or more."),
         "ingredient_source": FDA_QA,
         "legal_framing": ("Legal today: all 12 ingredients are permitted under the current US sunscreen monograph. "
                           "The FDA has proposed that they need more data before they can be recognized as safe and "
                           "effective. The finding is about what labels contain, not about any brand."),
         "numerator": len(more_data), "denominator": N, "population": POP,
         "detail": {"four_or_more": four_plus},
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot},
        {"id": "US-BABY-HOMOSALATE-EU", "status": "verified", "jurisdiction": "US",
         "ingredient_slugs": ["homosalate"], "finding": "homosalate-eu-limit",
         "claim": f"{homo_eu} of {N} baby/kids sunscreen formulations contain homosalate above 7.34%.",
         "publishable_sentence": (f"{homo_eu} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                  f"label database contain homosalate above 7.34%, the highest level the EU allows. "
                                  f"The EU allows it only in face products; the US allows up to 15% in any sunscreen."),
         "ingredient_source": EU_HOMOSALATE,
         "legal_framing": ("Legal in the US: the US monograph allows homosalate up to 15%. The EU and the US set "
                           "different limits; this finding compares them. It does not say any product breaks a rule "
                           "where it is sold."),
         "numerator": homo_eu, "denominator": N, "population": POP,
         "detail": {"homosalate_formulas": len(homo), "excluded_unreliable_percent": len(homo) - len(homo_ok),
                    "by_percent": by_percent},
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot},
    ]
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
