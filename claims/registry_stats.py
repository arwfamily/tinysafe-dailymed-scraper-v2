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
import re
import sys

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


EXCLUSIONS = os.path.join(ROOT, "claims", "population_exclusions.csv")
# SPLs that bundle several products but whose record holds one product's data
# (independent audit 2026-10-08).
MULTI_PRODUCT_SPL = {
    "c5d52f13-a649-9579-e053-2a95a90a062c": "kit: nasal spray, acne serum and sunscreen in one listing",
    "247aae3d-1845-4dd8-b774-b9e8214809a2": "two products in one listing; record holds one product's data",
    "3c470ff8-37d6-a729-e063-6294a90aa525": "two products in one listing; record holds one product's data",
    "43a6b8e3-49f7-2ac7-e054-00144ff88e88": "two products in one listing; record holds one product's data",
    "82771f22-0197-40ba-97d2-2386152790ed": "two products in one listing; first product is an adult spray",
}
_US_MAX = {"AVOBENZONE": 3, "OXYBENZONE": 6, "OCTINOXATE": 7.5, "HOMOSALATE": 15, "OCTISALATE": 5,
           "OCTOCRYLENE": 10, "ENSULIZOLE": 4, "ZINC OXIDE": 25, "TITANIUM DIOXIDE": 25}


def population_exclusion(r):
    """Reason this record is not a US baby sunscreen label as listed, or None."""
    if (r.get("product_count") or 1) > 1:
        return f"not one sunscreen: {r['product_count']} products in one listing"
    if r["setid"] in MULTI_PRODUCT_SPL:
        return "not one sunscreen: " + MULTI_PRODUCT_SPL[r["setid"]]
    if r.get("non_uv_actives"):
        return "not one sunscreen: non-sunscreen drug actives " + ", ".join(r["non_uv_actives"])
    t = r["title"].upper()
    m = re.search(r"\b(LATAM|FPS|CANADA)\b|OMBRELLE", t)
    if m:
        return f"label for another market (title says {m.group(0)})"
    if r.get("non_us_filter_active"):
        return "does not meet US rules as listed: active not permitted in the US (" + ", ".join(r["non_us_filter_active"]) + ")"
    for a in r.get("active_ingredients") or []:
        mx = _US_MAX.get((a.get("name") or "").upper())
        if mx is not None and (a.get("percent_ww") or 0) > mx + 0.01:
            return f"does not meet US rules as listed: {a['name'].lower()} {a['percent_ww']:g}% is above the US limit of {mx:g}%"
    return None


def load():
    # The decision ledger (scripts/baby_track.py) carries the 2026-10-08 hand
    # review forward and adds rule decisions for every new candidate.
    review = os.path.join(ROOT, "claims", "baby_decisions.csv")
    if not os.path.exists(review):
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
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from snapshot_and_history import formulation_fingerprint
    for r in recs:
        if r["setid"] in fixes:
            r.update(fixes[r["setid"]]["use"])
            r["_corrected"] = True
            # identity must follow the corrected formula, not the erroneous filing
            r["formulation_hash"] = formulation_fingerprint(r)[0]
    baby = [r for r in recs if r["setid"] in include]
    # Owner population is "labels that say baby or kids". Two kinds of record
    # are not a US baby sunscreen label and are left out, by rule, with reasons
    # written to claims/population_exclusions.csv.
    excl = []
    for r in baby:
        why = population_exclusion(r)
        if why:
            excl.append((r, why))
    with open(EXCLUSIONS, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["setid", "title", "reason", "dailymed"])
        for r, why in sorted(excl, key=lambda x: x[0]["title"]):
            w.writerow([r["setid"], r["title"], why, r["dailymed_url"]])
    out = {r["setid"] for r, _ in excl}
    baby = [r for r in baby if r["setid"] not in out]
    uniq = {}
    for r in sorted(baby, key=lambda r: r["setid"]):
        uniq.setdefault(r["formulation_hash"], r)
    return review, snapshot, list(uniq.values()), recs, include


def source(review, snapshot):
    return {"title": "FDA DailyMed SPL registry (structured product labels), ARW House analysis",
            "url": f"{REPO_URL}/data/canonical/us_sunscreens.jsonl",
            "list_url": f"{REPO_URL}/claims/{os.path.basename(review)}",
            "method_url": f"{REPO_URL}/claims/registry_stats.py",
            "snapshot": snapshot}


POP = ("unique formulations of sunscreen labels that say baby or kids "
       "(FDA DailyMed; selected by rule from the label, with edge cases decided by hand "
       "and every decision recorded with its reason; labels for another market, labels that do not "
       "meet US sunscreen limits as listed, and multi-product listings left out)")
POP_MIN = POP + "; mineral-only actives (zinc oxide and/or titanium dioxide)"
CAVEAT = ("DailyMed lists drug labels submitted to the FDA, including labels for products "
          "made in US facilities for other markets. A listing is not proof that a product "
          "is on US shelves today.")


PAIRS_CSV = os.path.join(ROOT, "claims", "same_ingredient_list_pairs.csv")
_FORMS = ["LOTION", "SPRAY", "STICK", "CREAM", "GEL", "OIL", "AEROSOL", "LIQUID", "MIST"]
_TITLE_ACTIVES = ["AVOBENZONE", "HOMOSALATE", "OCTISALATE", "OCTOCRYLENE", "OXYBENZONE", "OCTINOXATE",
                  "ZINC OXIDE", "TITANIUM"]


def same_list_pairs(forms, recs, include):
    """Baby/kids formulations whose DailyMed record lists exactly the same
    ingredients as a label that does not say baby or kids. Conservative:
      - same fingerprint v2 (actives at the same label percentage, same
        inactives in the same order)
      - the baby record has >=5 inactives and a label percentage for every active
      - the titles name the same actives, the same form (lotion/spray/...)
        and no conflicting SPF number
    """
    spf = lambda t: (lambda m: int(m.group(1)) if m else None)(re.search(r"(?:SPF|FPS)\s*(\d+)", t.upper()))
    form = lambda t: {f for f in _FORMS if re.search(r"\b" + f + r"\b", t.upper())}
    tact = lambda t: {w for w in _TITLE_ACTIVES if w in t.upper()}
    by = {}
    for r in recs:
        by.setdefault(r["formulation_hash"], []).append(r)
    out = []
    for r in forms:
        if len(r.get("inactive_ingredients") or []) < 5:
            continue
        if not all(isinstance(a.get("percent_ww"), (int, float)) for a in r.get("active_ingredients") or []):
            continue
        twins = [x for x in by.get(r["formulation_hash"], []) if x["setid"] not in include
                 and tact(x["title"]) == tact(r["title"]) and form(x["title"]) == form(r["title"])
                 and (not spf(x["title"]) or not spf(r["title"]) or spf(x["title"]) == spf(r["title"]))]
        if twins:
            out.append((r, sorted(twins, key=lambda x: x["setid"])))
    return out


def same_labeler(r, twins):
    return any((x.get("labeler_from_title") or "") == (r.get("labeler_from_title") or "") for x in twins)


# Synthetic ingredients in mineral-only sunscreens that their manufacturer
# describes as boosting SPF or stabilising UV filters, or that EU law lists as a
# UV filter. None is an FDA sunscreen active. Each entry carries the source of
# its function; an ingredient without a source is not counted (benzylidene
# dimethoxydimethylindanone was dropped: Symrise sells it as a skin-care agent,
# not a UV filter or booster).
BOOSTERS = [
    ("butyloctyl salicylate", r"\bBUTYLOCTYL SALICYLATE\b",
     "Hallstar, a manufacturer, says that at 5% it is responsible for no more than 2 SPF units on its own, that a larger SPF boost can be seen with other filters, and that it can help prevent the breakdown of certain UV filters.",
     "Butyloctyl Salicylate Q&A — Hallstar Beauty (manufacturer)", "https://www.hallstarbeauty.com/butyloctyl-salicylate-qa/"),
    ("ethylhexyl methoxycrylene", r"\bETHYLHEXYL METHOXYCRYLENE\b",
     "Hallstar sells it as SolaStay S1, a photostabilizer, and says it \"photostabilizes and improves mineral filter efficacy\".",
     "SolaStay S1 brochure — Hallstar Beauty (manufacturer)", "https://www.hallstarbeauty.com/webfoo/wp-content/uploads/SolaStay-S1-Brochure.pdf"),
    ("polyester-8", r"\bPOLYESTER-8\b",
     "Hallstar sells it as Polycrylene, a sunscreen photostabilizer, and lists \"SPF Enhancement\" as a feature.",
     "Polycrylene — Hallstar Beauty (manufacturer)", "https://www.hallstarbeauty.com/product/polycrylene/"),
    ("tridecyl salicylate", r"\bTRIDECYL SALICYLATE\b",
     "Vantage sells it as JEECHEM TDS, \"designed for use as a sunscreen booster\", and says it can be combined with titanium dioxide or zinc oxide.",
     "JEECHEM TDS — Vantage Specialty Ingredients (manufacturer)", "https://www.vantagegrp.com/en/Product/JEECHEM-TDS"),
    ("polysilicone-15", r"\bPOLYSILICONE-15\b",
     "A UV filter in the EU, allowed up to 10% under Annex VI of the EU Cosmetics Regulation. It is not an FDA sunscreen active.",
     "Polysilicone-15 — Cosmile Europe INCI database", "https://cosmileeurope.eu/inci/detail/12473/polysilicone-15/"),
    ("ethyl ferulate", r"\bETHYL FERULATE\b",
     "Sold as CaribSun UV, which its supplier describes as having \"antioxidant, free radical scavenging and UV adsorption properties\".",
     "CaribSun UV (Ethyl Ferulate) — UL Prospector", "https://ulprospector.com/en/na/PersonalCare/Products/25679/Esters/Functionalities/3699/Sunscreen-Agents"),
]


def full_ingredient_text(r):
    """Inactive ingredients as filed with the FDA plus the printed Drug Facts list."""
    filed = [(i.get("name") if isinstance(i, dict) else str(i)) or "" for i in r.get("inactive_ingredients") or []]
    return " | ".join(filed + list(r.get("printed_inactives") or [])).upper()


def boosters_in(r):
    t = full_ingredient_text(r)
    return [b[0] for b in BOOSTERS if re.search(b[1], t)]


# Preservatives that EU law no longer allows in cosmetics like these (in the EU
# a sunscreen is a cosmetic: Regulation (EC) 1223/2009, recital 7).
EU_BANNED = [
    ("isobutylparaben", r"ISOBUTYL ?PARABEN",
     "Banned from all cosmetics in the EU. Products containing it could no longer be made available on the EU market from July 30, 2015.",
     "Commission Regulation (EU) No 358/2014", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R0358"),
    ("methylisothiazolinone", r"(?<!CHLORO)METHYLISOTHIAZOLINONE",
     "Banned from leave-on cosmetics in the EU. Leave-on products containing it could no longer be made available on the EU market from February 12, 2017.",
     "Commission Regulation (EU) 2016/1198", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R1198"),
]
EU_COSMETIC_SOURCE = {"title": "Regulation (EC) No 1223/2009 on cosmetic products, recital 7 (sunbathing products)",
                      "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009R1223"}
FRAGRANCE = re.compile(r"\bFRAGRANCE\b|\bPARFUM\b|\bPERFUME\b")
AAD_FRAGRANCE = {"title": "How can I find eczema friendly products? — American Academy of Dermatology",
                 "url": "https://www.aad.org/public/diseases/eczema/childhood/triggers/friendly-products",
                 "checked": "2026-10-08"}


def ingredient_items(r):
    filed = [(i.get("name") if isinstance(i, dict) else str(i)) or "" for i in r.get("inactive_ingredients") or []]
    return filed, list(r.get("printed_inactives") or [])


def where_listed(r, pat):
    filed, printed = ingredient_items(r)
    out = []
    if any(re.search(pat, x.upper()) for x in filed):
        out.append("FDA filing")
    if any(re.search(pat, x.upper()) for x in printed):
        out.append("printed label")
    return out


def main():
    review, snapshot, forms, recs, include = load()
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
                                  f"label database contain at least one of the 12 active ingredients the FDA has proposed need more "
                                  f"safety data. {four_plus} of them contain four or more."),
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
                                  f"The EU allows it only in face products other than propellant sprays; the US allows up to 15% in any sunscreen."),
         "ingredient_source": EU_HOMOSALATE,
         "legal_framing": ("Legal in the US: the US monograph allows homosalate up to 15%. The EU and the US set "
                           "different limits; this finding compares them. It does not say any product breaks a rule "
                           "where it is sold."),
         "numerator": homo_eu, "denominator": N, "population": POP,
         "detail": {"homosalate_formulas": len(homo), "excluded_unreliable_percent": len(homo) - len(homo_ok),
                    "by_percent": by_percent},
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot},
    ]
    pairs = same_list_pairs(forms, recs, include)
    # Structured SPL tables can omit printed items (e.g. fragrance), so a pair
    # only counts once the printed Drug Facts lists were compared and matched.
    check_path = os.path.join(ROOT, "claims", "same_list_label_check.json")
    printed = {}
    if os.path.exists(check_path):
        for c in json.load(open(check_path, encoding="utf-8"))["pairs"]:
            printed[(c["baby"], c["other"])] = c["verdict"]
    checked_pairs = [(r, [x for x in t if printed.get((r["dailymed_url"], x["dailymed_url"])) == "match"]) for r, t in pairs]
    checked_pairs = [(r, t) for r, t in checked_pairs if t]
    pairs_checked_all = bool(printed) and all((r["dailymed_url"], x["dailymed_url"]) in printed for r, t in pairs for x in t)
    with open(PAIRS_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["baby_kids_title", "baby_kids_dailymed", "same_list_title", "same_list_dailymed", "same_company"])
        for r, twins in sorted(pairs, key=lambda p: p[0]["title"]):
            for x in twins:
                w.writerow([r["title"], r["dailymed_url"], x["title"], x["dailymed_url"],
                            "yes" if (x.get("labeler_from_title") or "") == (r.get("labeler_from_title") or "") else "no"])
    n_same_co = sum(1 for r, t in checked_pairs if same_labeler(r, t))
    claims.append({
        "id": "US-BABY-SAME-LIST", "status": "verified" if pairs_checked_all else "provisional_do_not_publish",
        "blocker": None if pairs_checked_all else "printed Drug Facts comparison (scripts/verify_same_list.py) not run for every candidate pair",
        "candidates_structured": len(pairs), "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "same-ingredient-list",
        "claim": f"{len(checked_pairs)} of {N} baby/kids formulations print the same ingredient list as a non-baby label.",
        "publishable_sentence": (f"{len(checked_pairs)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                 f"label database list the same ingredients in their Drug Facts as a sunscreen whose label does "
                                 f"not say baby or kids: the same active ingredients at the same percentages and the same "
                                 f"inactive ingredients in the same order. In at least {n_same_co} cases both labels name the "
                                 f"same labeler."),
        "legal_framing": ("Not a violation: nothing requires a baby or kids sunscreen to have a different formula. "
                          "The finding compares what the label records state; it does not show how the products are made."),
        "numerator": len(checked_pairs), "denominator": N, "population": POP,
        "detail": {"same_company": n_same_co, "pairs_csv": f"{REPO_URL}/claims/same_ingredient_list_pairs.csv",
                   "pairs": [{"baby": [r["title"], r["dailymed_url"]],
                              "same_list": [[x["title"], x["dailymed_url"]] for x in t],
                              "same_company": same_labeler(r, t)} for r, t in sorted(checked_pairs, key=lambda p: p[0]["title"])]},
        "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py (same_list_pairs)",
        "verified_date": snapshot})
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
         "ingredient_slugs": [], "superseded_finding": "mineral-sunscreen-boosters",
         "claim": f"{bos} of {M} mineral-only baby/kids sunscreen formulations contain butyloctyl salicylate.",
         "publishable_sentence": (f"{bos} of the {M} mineral baby and kids sunscreen formulas "
                                  f"listed in the FDA's DailyMed label database contain butyloctyl salicylate. It is not "
                                  f"an FDA sunscreen active ingredient. Hallstar, one of its manufacturers, says that at 5% it is "
                                  f"responsible for no more than 2 SPF units on its own, that a larger SPF boost can be seen "
                                  f"with other filters, and that it can help prevent the breakdown of certain UV filters."),
         "ingredient_source": {"title": "Butyloctyl Salicylate Q&A — Hallstar Beauty (manufacturer)",
                               "url": "https://www.hallstarbeauty.com/butyloctyl-salicylate-qa/",
                               "checked": "2026-10-08"},
         "legal_framing": ("Not a violation: butyloctyl salicylate is not an FDA sunscreen active, so it "
                           "belongs with the inactive ingredients, as the rules require. The finding is "
                           "about how labels work, not about any brand."),
         "numerator": bos, "denominator": M, "population": POP_MIN,
         "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py", "verified_date": snapshot},
    ]
    for c in claims:
        if c["id"] == "US-BABY-HIDDEN-UV":
            c["status"], c["superseded_by"] = "superseded", "US-BABY-MINERAL-BOOSTERS"
    hits = [(r, boosters_in(r)) for r in mineral]
    hits = [(r, b) for r, b in hits if b]
    per = collections.Counter(x for _, b in hits for x in b)
    claims.append({
        "id": "US-BABY-MINERAL-BOOSTERS", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "mineral-sunscreen-boosters",
        "claim": (f"{len(hits)} of {M} mineral-only baby/kids sunscreen formulations list at least one of "
                  f"{len(BOOSTERS)} synthetic SPF-boosting or UV-filter ingredients among their inactive ingredients."),
        "publishable_sentence": (f"{len(hits)} of the {M} mineral baby and kids sunscreen formulas listed in the FDA's "
                                 f"DailyMed label database also contain a synthetic ingredient that its manufacturer "
                                 f"sells to boost SPF or stabilize UV filters, or that the EU regulates as a UV filter. "
                                 f"It is listed under Inactive ingredients, not Active ingredients."),
        "legal_framing": ("Not a violation: none of these ingredients is an FDA sunscreen active, so they belong with "
                          "the inactive ingredients, as the rules require. The finding is about how labels work, not "
                          "about any brand."),
        "numerator": len(hits), "denominator": M, "population": POP_MIN,
        "detail": {
            "two_or_more": sum(1 for _, b in hits if len(b) >= 2),
            "ingredients": [{"name": n, "count": per[n], "function": fn,
                             "source": {"title": t, "url": u, "checked": "2026-10-08"}}
                            for n, _, fn, t, u in sorted(BOOSTERS, key=lambda b: -per[b[0]])],
            "formulas": [{"title": r["title"], "url": r["dailymed_url"], "boosters": b}
                         for r, b in sorted(hits, key=lambda h: (-len(h[1]), h[0]["title"]))],
            "lists_used": "inactive ingredients as filed with the FDA plus the printed Drug Facts ingredient list"},
        "caveat": CAVEAT, "site_source": src,
        "method": "claims/registry_stats.py (BOOSTERS, full_ingredient_text)", "verified_date": snapshot})

    # EU-banned preservatives
    eu_rows = []
    for r in forms:
        found = [(n, where_listed(r, pat)) for n, pat, *_ in EU_BANNED]
        found = [(n, w) for n, w in found if w]
        if found:
            ed = r.get("effective_date") or ""
            eu_rows.append({"title": r["title"], "url": r["dailymed_url"],
                            "label_date": f"{ed[:4]}-{ed[4:6]}-{ed[6:]}" if len(ed) == 8 else ed,
                            "ingredients": [n for n, _ in found], "listed_in": sorted({x for _, w in found for x in w})})
    eu_per = collections.Counter(n for row in eu_rows for n in row["ingredients"])
    claims.append({
        "id": "US-BABY-EU-BANNED-PRESERVATIVES", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "eu-banned-preservatives",
        "claim": (f"{len(eu_rows)} of {N} baby/kids sunscreen formulations list isobutylparaben "
                  f"({eu_per['isobutylparaben']}) or methylisothiazolinone ({eu_per['methylisothiazolinone']})."),
        "publishable_sentence": (f"{len(eu_rows)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                 f"label database list a preservative that the EU no longer allows in products like them: "
                                 f"isobutylparaben in {eu_per['isobutylparaben']}, banned from all EU cosmetics, and "
                                 f"methylisothiazolinone in {eu_per['methylisothiazolinone']}, banned from EU leave-on cosmetics."),
        "legal_framing": ("Not a violation in the US: neither preservative is banned in US sunscreens. In the EU a "
                          "sunscreen is a cosmetic, so EU cosmetics law applies to it. The finding compares label "
                          "records with EU law; it is not about any brand."),
        "numerator": len(eu_rows), "denominator": N, "population": POP,
        "ingredient_source": {"title": EU_BANNED[0][3], "url": EU_BANNED[0][4], "checked": "2026-10-08"},
        "detail": {
            "eu_cosmetic_source": EU_COSMETIC_SOURCE,
            "other_banned_parabens_found": sum(1 for r in forms if any(
                where_listed(r, pat) for pat in (r"ISOPROPYL ?PARABEN", r"PHENYL ?PARABEN", r"BENZYL ?PARABEN", r"PENTYL ?PARABEN"))),
            "ingredients": [{"name": n, "count": eu_per[n], "rule": rule, "source": {"title": t, "url": u, "checked": "2026-10-08"}}
                            for n, _, rule, t, u in EU_BANNED],
            "formulas": sorted(eu_rows, key=lambda x: (x["ingredients"], x["title"])),
            "oldest_label": min(x["label_date"] for x in eu_rows) if eu_rows else None,
            "newest_label": max(x["label_date"] for x in eu_rows) if eu_rows else None},
        "caveat": CAVEAT, "site_source": src,
        "method": "claims/registry_stats.py (EU_BANNED, where_listed)", "verified_date": snapshot})

    # Fragrance
    fr = [r for r in forms if any(FRAGRANCE.search(x.upper()) for x in sum(ingredient_items(r), []))]
    fr_min = sum(1 for r in fr if r.get("is_mineral_only_actives"))
    claims.append({
        "id": "US-BABY-FRAGRANCE", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "fragrance",
        "claim": f"{len(fr)} of {N} baby/kids sunscreen formulations list fragrance (or parfum) as an ingredient.",
        "publishable_sentence": (f"{len(fr)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed label "
                                 f"database list fragrance (or parfum) as an ingredient. For children with eczema, the "
                                 f"American Academy of Dermatology advises a sunscreen that is fragrance-free."),
        "legal_framing": ("Not a violation: fragrance is allowed in US sunscreens. The finding counts what the "
                          "ingredient lists say; it is not about any brand."),
        "numerator": len(fr), "denominator": N, "population": POP,
        "ingredient_source": AAD_FRAGRANCE,
        "detail": {"mineral": [fr_min, M], "other": [len(fr) - fr_min, N - M],
                   "formulas": [{"title": r["title"], "url": r["dailymed_url"],
                                 "mineral": bool(r.get("is_mineral_only_actives")),
                                 "listed_in": where_listed(r, FRAGRANCE.pattern)}
                                for r in sorted(fr, key=lambda r: r["title"])],
                   "not_counted": "essential oils and other single scent ingredients; only fragrance, parfum or perfume"},
        "caveat": CAVEAT, "site_source": src,
        "method": "claims/registry_stats.py (FRAGRANCE)", "verified_date": snapshot})

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
