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
# Labels whose only artwork is for another market, seen in the label image
# (data/corrections/printed_lists_from_images.jsonl notes).
OTHER_MARKET_SPL = {
    # Language alone does not make a label foreign (owner decision 2026-10-08:
    # a Korean-only carton listed in DailyMed stays in); a named foreign
    # importer does.
    "13c9ab06-9903-728a-e054-00144ff88e88": "label names a Brazilian importer (Mappel); Portuguese artwork, no US Drug Facts",
}
MULTI_PRODUCT_SPL = {
    "c5d52f13-a649-9579-e053-2a95a90a062c": "kit: nasal spray, acne serum and sunscreen in one listing",
    "247aae3d-1845-4dd8-b774-b9e8214809a2": "two products in one listing; record holds one product's data",
    "3c470ff8-37d6-a729-e063-6294a90aa525": "two products in one listing; record holds one product's data",
    "43a6b8e3-49f7-2ac7-e054-00144ff88e88": "two products in one listing; record holds one product's data",
    "82771f22-0197-40ba-97d2-2386152790ed": "two products in one listing; first product is an adult spray",
}
_US_MAX = {"AVOBENZONE": 3, "OXYBENZONE": 6, "OCTINOXATE": 7.5, "HOMOSALATE": 15, "OCTISALATE": 5,
           "OCTOCRYLENE": 10, "ENSULIZOLE": 4, "ZINC OXIDE": 25, "TITANIUM DIOXIDE": 25}


_TEXT = None
_DIST = re.compile(r"(?:DISTRIBUTED BY|DISTRIBU[ÉE] PAR|IMPORTED BY|IMPORT[ÉE] PAR|IMPORTADO Y DISTRIBUIDO POR|DISTRIBUIDO POR)\W{0,3}(.{0,140})", re.I)
_ABROAD = [("Mexico", r"M[ÉE]XICO"), ("Canada", r"CANADA|\bON N\d|\bQC\b|ONTARIO|QU[ÉE]BEC|,\s*(?:ON|BC|AB|MB|SK|NS|NB)\b(?!\s*\d{5})"),
           ("the UK", r"\bUK\b|UNITED KINGDOM|HIGH WYCOMBE"), ("Australia", r"AUSTRALIA")]
_US = re.compile(r"\bU\.?S\.?A\b|UNITED STATES|,\s?[A-Z]{2}\.?\s?\d{5}\b", re.I)


def other_market_text(setid):
    """Country of a non-US distributor/importer named on the label, when the
    label names no US distributor (label-text archive). 'Made in Canada' alone
    is not another market, and 'Made in U.S.A.' after a foreign distributor
    does not make the label a US one."""
    global _TEXT
    if _TEXT is None:
        _TEXT = {}
        if os.path.exists(LABEL_TEXT):
            for line in open(LABEL_TEXT, encoding="utf-8"):
                d = json.loads(line)
                _TEXT[d["setid"]] = d.get("text") or ""
    t = _TEXT.get(setid, "")
    foreign, us = None, False
    for m in _DIST.finditer(t):
        clause = re.split(r"MADE IN|FABRIQU|MANUFACTURED BY|\|", m.group(1), flags=re.I)[0]
        if _US.search(clause):  # 'ONTARIO, CA 91761' is California
            us = True
            continue
        hit = next((c for c, pat in _ABROAD if re.search(pat, clause, re.I)), None)
        if hit:
            foreign = foreign or hit
    return foreign if foreign and not us else None


def population_exclusion(r):
    """Reason this record is not a US baby sunscreen label as listed, or None."""
    if (r.get("product_count") or 1) > 1:
        return f"not one sunscreen: {r['product_count']} products in one listing"
    if r["setid"] in MULTI_PRODUCT_SPL:
        return "not one sunscreen: " + MULTI_PRODUCT_SPL[r["setid"]]
    if r.get("non_uv_actives"):
        return "not one sunscreen: non-sunscreen drug actives " + ", ".join(r["non_uv_actives"])
    if r["setid"] in OTHER_MARKET_SPL:
        return "label for another market: " + OTHER_MARKET_SPL[r["setid"]]
    om = other_market_text(r["setid"])
    if om:
        return f"label for another market (label names a distributor or importer in {om})"
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


_PRODUCTS = None


def split_listing(r):
    """Products of a multi-product listing as records of their own (from the
    label-text archive, which keeps each product's structured ingredients)."""
    global _PRODUCTS
    if _PRODUCTS is None:
        _PRODUCTS = {}
        if os.path.exists(LABEL_TEXT):
            for line in open(LABEL_TEXT, encoding="utf-8"):
                d = json.loads(line)
                _PRODUCTS[d["setid"]] = d.get("products") or []
    out = []
    labeler = re.search(r"\[([^\]]+)\]\s*$", r["title"])
    for i, p in enumerate(_PRODUCTS.get(r["setid"], [])):
        if not p.get("actives"):
            continue
        acts = [{"name": a["name"], "unii": a.get("unii"), "percent_ww": a.get("percent_structured")}
                for a in p["actives"]]
        name = (p.get("name") or "").upper()
        out.append({
            "setid": f"{r['setid']}#{i + 1}",
            # classified by its own name only; the listing is kept for reference
            "title": f"{name} [{labeler.group(1) if labeler else ''}]",
            "listing_title": r["title"], "part": f"product {i + 1} of {len(_PRODUCTS[r['setid']])} in one listing",
            "product_name": name, "active_ingredients": acts,
            "inactive_ingredients": p.get("inactives") or [], "printed_inactives": None,
            "dosage_form": p.get("dosage_form"), "product_count": 1, "label_flags": r.get("label_flags"),
            "effective_date": r.get("effective_date"), "dailymed_url": r["dailymed_url"],
            "labeler": r.get("labeler"), "listing_setid": r["setid"]})
    # When some products in the listing name babies or kids, only those count;
    # when none does, the listing's own baby/kids title stands for all of them.
    from classify import BABY_RE
    named = [p for p in out if BABY_RE.search(p["product_name"])]
    return named or out


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
    # A listing that bundles several products is split into its products; each
    # product that is itself a sunscreen meeting the same rules joins the
    # population as its own formula (its ingredients come from the filing,
    # because the printed Drug Facts on such a label cover several products).
    from classify import classify
    parts_added = []
    for r, why in excl:
        if not why.startswith("not one sunscreen:") or "non-sunscreen drug actives" in why:
            continue
        for sub in split_listing(r):
            sub.update(classify(sub))
            sub["formulation_hash"] = formulation_fingerprint(sub)[0]
            if sub.get("product_type") == "sunscreen" and not population_exclusion(sub):
                parts_added.append(sub)
    baby += parts_added
    # The formulation hash is built from the FDA filing, and filings often omit
    # fragrance (see the fragrance finding). A scented and an unscented product
    # with the same filing are different formulas, so the printed label's
    # fragrance splits them.
    # A label whose printed list is only an image tells us nothing about
    # fragrance, so it never starts a group of its own.
    def scent(r):
        if where_listed(r, FRAGRANCE.pattern):
            return True
        has_text = len(r.get("printed_inactives") or []) >= FULL_PRINTED_LIST or len(printed_section(r["setid"])) >= 60
        return False if has_text else None
    uniq = {}
    for r in sorted(baby, key=lambda r: (scent(r) is None, r["setid"])):
        k = scent(r)
        if k is None:
            k = next((kk for kk in uniq if kk[0] == r["formulation_hash"]), (r["formulation_hash"], None))
        uniq.setdefault((r["formulation_hash"], k[1] if isinstance(k, tuple) else k), r)
    return review, snapshot, list(uniq.values()), recs, include


def source(review, snapshot):
    return {"title": "FDA DailyMed SPL registry (structured product labels), ARW House analysis",
            "url": f"{REPO_URL}/data/canonical/us_sunscreens.jsonl",
            "list_url": f"{REPO_URL}/claims/{os.path.basename(review)}",
            "method_url": f"{REPO_URL}/claims/registry_stats.py",
            "snapshot": snapshot}


POP = ("unique formulations of sunscreen labels that say baby or kids in the product name or on the "
       "front panel, plus the sunscreens of baby-care brands (Tubby Todd, Pipette, Mustela, Babo Botanicals, "
       "Babyganics, California Baby, Thinkbaby, Sqween, Putto; tinted and lip products excluded) "
       "(FDA DailyMed; selected by rule from the label, with edge cases decided by hand "
       "and every decision recorded with its reason; a claim such as 'suitable for children' alone does "
       "not count; labels that name a foreign distributor or importer and labels that do not meet US "
       "sunscreen limits as listed left out; a listing that bundles several products is split into its products)")
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


def _nk(x):
    x = x.upper().replace("\u2010", "-").replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    x = re.sub(r"\(\s*1\s*\)|[\*\u2020\u2021\u00b0\u00b9\^]+", "", x)
    x = re.sub(r"^(?:SECTION\s*/?\s*)?(?:INACTIVE |OTHER )?INGREDIENTS?\s*:?\s*", "", x)
    return re.sub(r"[^A-Z0-9]", "", x)


def printed_items(r):
    """The label's printed inactive list as normalised items (label text,
    archived Drug Facts text or image transcription), or []."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from spl_parse import split_ingredient_list
    sec = printed_section(r["setid"]) if not str(r["setid"]).count("#") else ""
    items = split_ingredient_list(re.sub(r"^INACTIVE INGREDIENTS \(TRANSCRIBED FROM LABEL IMAGE\):\s*", "Inactive ingredients: ", sec)) if sec else []
    if len(items) < 5:
        items = list(r.get("printed_inactives") or [])
    # a stray "s" or "(s)" left from a cut heading ("Ingredient(s) Beeswax") is not part
    # of the first ingredient
    items = [re.sub(r"^\s*\(?[sS]\)?\s+(?=\S)", "", x) if n == 0 else x for n, x in enumerate(items)]
    return [k for k in (_nk(i) for i in items) if k]


def _form(r):
    f = (r.get("dosage_form") or "").upper()
    return "SPRAY" if "SPRAY" in f or "AEROSOL" in f else f


def _actives_key(r):
    out = []
    for a in r.get("active_ingredients") or []:
        if not isinstance(a.get("percent_ww"), (int, float)):
            return None
        out.append(((a.get("unii") or a.get("name") or "").upper(), round(a["percent_ww"], 1)))
    return tuple(sorted(out)) or None


def same_list_printed(forms, recs, include):
    """Baby/kids formulas whose printed inactive list (>= 5 items, in order),
    actives at the same percentages and product form equal those of a sunscreen
    label that does not say baby or kids anywhere we can read."""
    by = {}
    for x in recs:
        if x["setid"] in include or x.get("product_type") != "sunscreen":
            continue
        # the other label must not say baby or kids in its name or on its front
        # panel; a baby-brand label or a 'pediatrician tested' claim alone does not
        if x.get("baby_signal") in ("product_name", "brand_name"):
            continue
        if set((x.get("label_flags") or {}).get("front_panel_baby_words") or []) - {"PEDIATRIC", "PAEDIATRIC", "CHILD", "CHILDREN"}:
            continue
        k = _actives_key(x)
        if k:
            by.setdefault((k, _form(x)), []).append(x)
    # every baby/kids label of a formula, not only its representative: labels
    # of one formula can print their list differently
    members = {}
    for x in recs:
        if x["setid"] in include:
            members.setdefault(x["formulation_hash"], []).append(x)
    out = []
    for r in forms:
        k = _actives_key(r)
        if not k:
            continue
        scent = bool(where_listed(r, FRAGRANCE.pattern))
        group = [r] + [x for x in members.get(r["formulation_hash"], []) if x["setid"] != r["setid"]
                       and _actives_key(x) == k and _form(x) == _form(r)
                       and bool(where_listed(x, FRAGRANCE.pattern)) == scent]
        # compared as one joined string: the same words in the same order,
        # whatever the label's comma placement ('Caprylic/Capric' 'Triglyceride')
        lists = {"".join(l) for l in (printed_items(x) for x in group) if len(l) >= 5}
        if not lists:
            continue
        twins = [x for x in by.get((k, _form(r)), [])
                 if len(printed_items(x)) >= 5 and "".join(printed_items(x)) in lists]
        if twins:
            out.append((r, sorted(twins, key=lambda x: x["setid"])))
    return out


def _co(name):
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"\b(INC|LLC|LTD|CO|CORP|CORPORATION|COMPANY)\b\.?", "", (name or "").upper()))


def same_labeler(r, twins):
    return any(_co(x.get("labeler_from_title")) == _co(r.get("labeler_from_title")) for x in twins)


# Synthetic ingredients in mineral-only sunscreens that their manufacturer
# describes as boosting SPF or stabilising UV filters, or that EU law lists as a
# UV filter. None is an FDA sunscreen active. Each entry carries the source of
# its function; an ingredient without a source is not counted (benzylidene
# dimethoxydimethylindanone was dropped: Symrise sells it as a skin-care agent,
# not a UV filter or booster).
BOOSTERS = [
    ("butyloctyl salicylate", r"\bBUT[YL]{2} ?OC?T?Y[LI] ?SA[LI]{1,2}CYLATE\b",
     "Hallstar, a manufacturer, says that at 5% it is responsible for no more than 2 SPF units on its own, that a larger SPF boost can be seen with other filters, and that it can help prevent the breakdown of certain UV filters.",
     "Butyloctyl Salicylate Q&A — Hallstar Beauty (manufacturer)", "https://www.hallstarbeauty.com/butyloctyl-salicylate-qa/"),
    ("ethylhexyl methoxycrylene", r"\bETHYLHEXYL METHO?X?Y?CRYLENE\b",
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
    return [b[0] for b in BOOSTERS if where_listed(r, b[1])]


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
# No word boundaries: some labels print ingredients run together
# ("DIMETHICONEFRAGRANCENEOPENTYL", "FRAGRANCEPRODUCT FORMULATED WITH").
FRAGRANCE = re.compile(r"FRAGRANCE(?![- ]?FREE)|PARFUM|PERFUME")
AAD_FRAGRANCE = {"title": "How can I find eczema friendly products? — American Academy of Dermatology",
                 "url": "https://www.aad.org/public/diseases/eczema/childhood/triggers/friendly-products",
                 "checked": "2026-10-08"}


def ingredient_items(r):
    filed = [(i.get("name") if isinstance(i, dict) else str(i)) or "" for i in r.get("inactive_ingredients") or []]
    return filed, list(r.get("printed_inactives") or [])


FULL_PRINTED_LIST = 8   # a printed list this long is read as the complete label list
LABEL_TEXT = os.path.join(ROOT, "data", "views", "baby_label_text.jsonl")
_SECTION = None


_FULLTEXT = {}
_FOOT = {}   # footnotes printed under a transcribed list ("*Fragrance (Parfum)")


def _unheaded_list(text, items):
    """The ' | '-delimited block of label text that contains at least 60% of the
    transcribed items, or ''."""
    def key(x):
        return re.sub(r"[^A-Z0-9]", "", re.sub(r"\(\s*1\s*\)|\*", "", x.upper()))
    want = [key(i) for i in items if key(i)]
    best, score = "", 0.0
    for block in text.split(" | "):
        b = re.sub(r"[^A-Z0-9]", "", block.upper())
        if not want or len(b) < 40:
            continue
        sc = sum(1 for w in want if w and w in b) / len(want)
        if sc > score:
            best, score = block, sc
    return best if score >= 0.6 else ""


def printed_section(setid):
    """The Inactive ingredients text printed on the label (from the label-text
    archive, scripts/baby_label_text.py), or '' if the label has none in text."""
    global _SECTION
    if _SECTION is None:
        _SECTION = {}
        if os.path.exists(LABEL_TEXT):
            for line in open(LABEL_TEXT, encoding="utf-8"):
                d = json.loads(line)
                secs = d.get("sections") or {}
                txt = " ".join(v for k, v in secs.items() if re.search(r"INACTIVE|^INGREDIENTS|^OTHER INGREDIENTS", k.upper()))
                if not txt:
                    m = re.search(r"(?:INACTIVE|OTHER) INGREDIENTS?[^|]{40,}", (d.get("text") or "").upper())
                    txt = m.group(0) if m else ""
                _SECTION[d["setid"]] = txt.upper()
                _FULLTEXT[d["setid"]] = d.get("text") or ""
        # Image-only lists, transcribed from the label image twice and agreed
        # (data/corrections/printed_lists_from_images.jsonl).
        tx = os.path.join(ROOT, "data", "corrections", "printed_lists_from_images.jsonl")
        if os.path.exists(tx):
            for line in open(tx, encoding="utf-8"):
                t = json.loads(line)
                # a list in another script (e.g. Korean) cannot be matched to
                # English ingredient names; the filing decides for that label
                english = t.get("items") and sum(ch.isascii() for ch in "".join(t["items"])) > 0.9 * len("".join(t["items"]))
                if english and t.get("footnotes"):
                    fn = t["footnotes"]
                    _FOOT[t["setid"]] = (" ".join(fn) if isinstance(fn, list) else str(fn)).upper()
                if english and t.get("overrides_text"):
                    _SECTION[t["setid"]] = ("INACTIVE INGREDIENTS (TRANSCRIBED FROM LABEL IMAGE): " + ", ".join(t["items"])).upper()
                elif english and len(_SECTION.get(t["setid"], "")) < 60:
                    # The SPL text may carry the list without a heading. If a
                    # text block holds most of the transcribed items, that text
                    # is the label's current list and decides (an image can be
                    # older artwork: Jason Kids, 2026-10-09 audit).
                    block = _unheaded_list(_FULLTEXT.get(t["setid"], ""), t["items"])
                    _SECTION[t["setid"]] = block.upper() if block else (
                        "INACTIVE INGREDIENTS (TRANSCRIBED FROM LABEL IMAGE): " + ", ".join(t["items"])).upper()
    return _SECTION.get(setid, "")


def _loose(pat):
    """Pattern for label text with spaces and hyphens removed."""
    return re.sub(r"\\b|\(\?<![^)]*\)| \?| ", "", pat).replace("-", "")


def where_listed(r, pat):
    """Where an ingredient is listed: [] if not counted.
    The printed label decides whenever it carries its ingredient list as text:
      1. a parsed printed list of FULL_PRINTED_LIST+ items, or the label's
         Inactive ingredients text, mentions it -> counted;
      2. the label prints its list as text but it is not there -> NOT counted,
         even if the FDA filing has it (the filing and the label disagree);
      3. the label's list is an image (no text) -> the FDA filing decides.
    The text check also tries the pattern with spaces removed, for labels
    printed without separators; a looser match can only keep a filed
    ingredient, never add one. Typos are handled in the patterns themselves,
    never by fuzzy matching (polyester-7 vs polyester-8)."""
    filed, printed = ingredient_items(r)
    in_filed = any(re.search(pat, x.upper()) for x in filed)
    in_list = any(re.search(pat, x.upper()) for x in printed)
    sec = printed_section(r["setid"])
    foot = _FOOT.get(r["setid"], "") if sec.startswith("INACTIVE INGREDIENTS (TRANSCRIBED") else ""
    in_sec = bool(sec) and (re.search(pat, sec + " | " + foot) is not None)
    # The squashed-text check cannot see word boundaries, so it is not used for
    # names that differ only by a prefix (methyl/ethyl, butyl/isobutyl).
    loose = (bool(sec) and in_filed and "(?" not in pat
             and re.search(_loose(pat), re.sub(r"[^A-Z0-9]", "", sec)) is not None)
    if in_list or in_sec:
        return ["printed label", "FDA filing"] if in_filed else ["printed label"]
    if len(printed) >= FULL_PRINTED_LIST or len(sec) >= 60:
        return ["printed label", "FDA filing"] if loose else []
    return ["FDA filing"] if in_filed else []


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
    # Same printed ingredient list: compared directly on the printed Drug
    # Facts of both labels (label text, or the image transcription), across
    # every sunscreen label in DailyMed, not only labels with the same filing.
    checked_pairs = same_list_printed(forms, recs, include)
    with open(os.path.join(ROOT, "claims", "same_ingredient_list_pairs_published.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["baby_kids_title", "baby_kids_dailymed", "same_list_title", "same_list_dailymed", "same_labeler",
                    "printed_items"])
        for r, twins in sorted(checked_pairs, key=lambda p: p[0]["title"]):
            for x in twins:
                w.writerow([r["title"], r["dailymed_url"], x["title"], x["dailymed_url"],
                            "yes" if _co(x.get("labeler_from_title")) == _co(r.get("labeler_from_title")) else "no",
                            len(printed_items(r))])
    pairs_checked_all = True
    pairs = checked_pairs
    n_same_co = sum(1 for r, t in checked_pairs if same_labeler(r, t))
    claims.append({
        "id": "US-BABY-SAME-LIST", "status": "verified" if pairs_checked_all else "provisional_do_not_publish",
        "jurisdiction": "US",
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
        "detail": {"same_company": n_same_co, "pairs_csv": f"{REPO_URL}/claims/same_ingredient_list_pairs_published.csv",
                   "pairs": [{"baby": [r["title"], r["dailymed_url"]],
                              "same_list": [[x["title"], x["dailymed_url"]] for x in t],
                              "same_company": same_labeler(r, t)} for r, t in sorted(checked_pairs, key=lambda p: p[0]["title"])]},
        "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py (same_list_printed)",
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
         "ingredient_slugs": [], "superseded_finding": "spf-boosters",
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
            c["status"], c["superseded_by"] = "superseded", "US-BABY-BOOSTERS"
    hits = [(r, boosters_in(r)) for r in forms]
    hits = [(r, b) for r, b in hits if b]
    per = collections.Counter(x for _, b in hits for x in b)
    per_m = collections.Counter(x for r, b in hits if r.get("is_mineral_only_actives") for x in b)
    hm = sum(1 for r, _ in hits if r.get("is_mineral_only_actives"))
    claims.append({
        "id": "US-BABY-BOOSTERS", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "spf-boosters",
        "claim": (f"{len(hits)} of {N} baby/kids sunscreen formulations ({hm} of {M} mineral-only) list at least one of "
                  f"{len(BOOSTERS)} synthetic SPF-boosting or UV-filter ingredients among their inactive ingredients."),
        "publishable_sentence": (f"{len(hits)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                 f"label database contain a synthetic ingredient that its manufacturer sells to boost SPF "
                                 f"or stabilize UV filters, or that the EU regulates as a UV filter, listed under Inactive "
                                 f"ingredients. That includes {hm} of the {M} mineral formulas, whose only active "
                                 f"ingredients are zinc oxide and/or titanium dioxide."),
        "legal_framing": ("Not a violation: none of these ingredients is an FDA sunscreen active, so they belong with "
                          "the inactive ingredients, as the rules require. The finding is about how labels work, not "
                          "about any brand."),
        "numerator": len(hits), "denominator": N, "population": POP,
        "detail": {
            "mineral": [hm, M], "other": [len(hits) - hm, N - M],
            "two_or_more": sum(1 for _, b in hits if len(b) >= 2),
            "ingredients": [{"name": n, "count": per[n], "mineral": per_m[n], "function": fn,
                             "source": {"title": t, "url": u, "checked": "2026-10-08"}}
                            for n, _, fn, t, u in sorted(BOOSTERS, key=lambda b: -per[b[0]])],
            "formulas": [{"title": r["title"], "url": r["dailymed_url"], "boosters": b,
                          "mineral": bool(r.get("is_mineral_only_actives"))}
                         for r, b in sorted(hits, key=lambda h: (not h[0].get("is_mineral_only_actives"), -len(h[1]), h[0]["title"]))],
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

    # Hawaii: oxybenzone / octinoxate (HRS 342D-21, from January 1, 2021)
    hi_rows = []
    for r in forms:
        got = sorted(set(r.get("uv_filters_organic") or []) & {"oxybenzone", "octinoxate"})
        if got:
            ed = r.get("effective_date") or ""
            hi_rows.append({"title": r["title"], "url": r["dailymed_url"], "filters": got,
                            "label_date": f"{ed[:4]}-{ed[4:6]}-{ed[6:]}" if len(ed) == 8 else ed})
    hi_per = collections.Counter(x for row in hi_rows for x in row["filters"])
    hi_recent = sum(1 for x in hi_rows if x["label_date"] >= "2021-01-01")
    claims.append({
        "id": "US-BABY-HAWAII", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": ["oxybenzone", "octinoxate"], "finding": "hawaii-oxybenzone-octinoxate",
        "claim": (f"{len(hi_rows)} of {N} baby/kids sunscreen formulations list oxybenzone ({hi_per['oxybenzone']}) "
                  f"or octinoxate ({hi_per['octinoxate']}) as an active ingredient."),
        "publishable_sentence": (f"{len(hi_rows)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                 f"label database contain oxybenzone or octinoxate. Since January 1, 2021, Hawaii law has "
                                 f"made it unlawful to sell, offer for sale or distribute for sale in the state a sunscreen "
                                 f"containing either one without a prescription."),
        "legal_framing": ("Both ingredients are permitted under the FDA sunscreen monograph. Hawaii's law applies to sales "
                          "in Hawaii only, and a DailyMed listing does not show where, or whether, a product is sold."),
        "numerator": len(hi_rows), "denominator": N, "population": POP,
        "ingredient_source": {"title": "Hawaii Revised Statutes §342D-21 (L 2018, c 104, §2)",
                              "url": "https://law.justia.com/codes/hawaii/title-19/chapter-342d/section-342d-21/",
                              "checked": "2026-10-08"},
        "detail": {"per_filter": [["oxybenzone", hi_per["oxybenzone"]], ["octinoxate", hi_per["octinoxate"]]],
                   "both": sum(1 for x in hi_rows if len(x["filters"]) == 2),
                   "label_updated_since_2021": hi_recent,
                   "act_text": {"title": "SB2571 CD1 (2018), enacted as Act 104", "url": "https://www.legiscan.com/HI/text/SB2571/2018"},
                   "formulas": sorted(hi_rows, key=lambda x: (x["label_date"], x["title"]), reverse=True)},
        "caveat": CAVEAT, "site_source": src,
        "method": "claims/registry_stats.py (Hawaii)", "verified_date": snapshot})

    # Sprays (AAP: lotions to avoid inhalation, or spray onto hands first)
    def is_spray(r):
        f = (r.get("dosage_form") or "").upper()
        if "FOAM" in f:
            return False
        name = (r.get("product_name") or r["title"]).upper()
        return "SPRAY" in f or re.search(r"\bSPRAY|\bMIST\b", name) is not None
    sp = [r for r in forms if is_spray(r)]
    sp_min = sum(1 for r in sp if r.get("is_mineral_only_actives"))
    labelers = {_co(r.get("labeler_from_title") or r.get("labeler")) for r in sp}
    claims.append({
        "id": "US-BABY-SPRAYS", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "sprays",
        "claim": f"{len(sp)} of {N} baby/kids sunscreen formulations are sprays ({sp_min} of {M} mineral-only).",
        "publishable_sentence": (f"{len(sp)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed label "
                                 f"database are sprays, from {len(labelers)} labelers. To avoid inhalation, the American "
                                 f"Academy of Pediatrics suggests lotions, or, if a spray is used, spraying it onto the hands "
                                 f"and then applying it to the child."),
        "legal_framing": ("Not a violation: spray is a permitted sunscreen form in the US. The FDA has proposed that spray "
                          "sunscreens remain generally recognized as safe and effective subject to testing and labeling "
                          "requirements."),
        "numerator": len(sp), "denominator": N, "population": POP,
        "ingredient_source": {"title": "Chemical Exposure from Personal Care Products — American Academy of Pediatrics",
                              "url": "https://www.aap.org/en/patient-care/environmental-health/promoting-healthy-environments-for-children/personal-care-products/",
                              "checked": "2026-10-09"},
        "detail": {"mineral": [sp_min, M], "other": [len(sp) - sp_min, N - M], "labelers": len(labelers),
                   "healthychildren": {"title": "What's the best way to protect kids' skin from sunburn? — HealthyChildren.org (AAP)",
                                       "url": "https://www.healthychildren.org/English/tips-tools/ask-the-pediatrician/Pages/whats-the-best-way-to-protect-kids-skin-from-sunburn.aspx",
                                       "checked": "2026-10-09"},
                   "fda": {"title": "Questions and Answers: FDA's regulatory actions on OTC sunscreen",
                           "url": "https://www.fda.gov/drugs/understanding-over-counter-medicines/questions-and-answers-fdas-regulatory-actions-over-counter-sunscreen"},
                   "formulas": [{"title": r["title"], "url": r["dailymed_url"], "form": r.get("dosage_form"),
                                 "mineral": bool(r.get("is_mineral_only_actives"))}
                                for r in sorted(sp, key=lambda r: r["title"])]},
        "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py (sprays)", "verified_date": snapshot})

    # "Mineral" on the front, chemical UV filters in the actives. The wording is
    # read from the printed front panel (text or label image) by a person and
    # recorded with its evidence in data/corrections/front_mineral_wording.jsonl.
    # Every baby/kids label that mixes mineral and chemical actives, or whose
    # text says mineral, must have a reviewed entry; new ones are printed in
    # the run log and listed as unreviewed, and count only once reviewed.
    mw = {}
    mwp = os.path.join(ROOT, "data", "corrections", "front_mineral_wording.jsonl")
    if os.path.exists(mwp):
        for line in open(mwp, encoding="utf-8"):
            if line.strip():
                x = json.loads(line)
                mw[x["setid"]] = x
    texts = {}
    for line in open(LABEL_TEXT, encoding="utf-8"):
        x = json.loads(line)
        texts[x["setid"]] = x
    _MIN_WORD = re.compile(r"\bMINERAL(?![- ]?OIL)(?!S? ?\(PARAFFINUM)", re.I)

    def front_text(sid):
        secs = (texts.get(sid) or {}).get("sections") or {}
        return " ".join(v for k, v in secs.items()
                        if not re.search(r"INACTIVE|INGREDIENT|DRUG FACTS|WARNING|DIRECTION|USES?$|PURPOSE|OTHER INFO", k.upper()))
    pop_labels = [r for r in recs if r["setid"] in include] + [r for r in forms if r["setid"] not in include]
    candidates, unreviewed = set(), []
    for r in pop_labels:
        if not orgs(r):
            continue
        name = (r.get("product_name") or "") + " " + r["title"]
        if r.get("uv_filters_mineral") or _MIN_WORD.search(name) or _MIN_WORD.search(front_text(r["setid"])):
            candidates.add(r["setid"])
            if r["setid"] not in mw:
                unreviewed.append({"setid": r["setid"], "title": r["title"]})
    form_of = {r["formulation_hash"]: r for r in forms}
    mrows = {}
    for sid, x in mw.items():
        if x["front_wording"] != "says_mineral":
            continue
        r = next((rr for rr in pop_labels if rr["setid"] == sid), None)
        if r is None or not orgs(r):
            continue
        rep = form_of.get(r["formulation_hash"])
        if rep is None:
            continue
        mrows.setdefault(rep["formulation_hash"], {
            "title": r["title"], "url": r["dailymed_url"], "phrase": x["phrase"], "evidence": x["evidence"],
            "chemical_filters": sorted(orgs(r)), "mineral_filters": sorted(r.get("uv_filters_mineral") or []),
            "form": r.get("dosage_form"), "discloses_chemical": bool(re.search(r"chemical", x["phrase"], re.I))})
    mrows = sorted(mrows.values(), key=lambda x: x["title"])
    name_only = [{"title": next((rr["title"] for rr in pop_labels if rr["setid"] == s), s),
                  "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={s}", "evidence": x["evidence"]}
                 for s, x in mw.items() if x["front_wording"] == "name_only" and s in candidates]
    combo_forms = sum(1 for r in forms if orgs(r) and r.get("uv_filters_mineral"))
    if unreviewed:
        print(f"[registry_stats] mineral wording: {len(unreviewed)} labels need a front-panel check: "
              + "; ".join(u["title"][:60] for u in unreviewed))
    claims.append({
        "id": "US-BABY-MINERAL-WORDING", "status": "verified",
        "jurisdiction": "US", "ingredient_slugs": [], "finding": "mineral-wording",
        "claim": (f"{len(mrows)} of {N} baby/kids sunscreen formulations say 'mineral' on the front of the label "
                  f"and also contain organic (chemical) UV filters."),
        "publishable_sentence": (f"{len(mrows)} baby and kids sunscreen formulas listed in the FDA's DailyMed label "
                                 f"database say “mineral” on the front of the package, such as “mineral-based” or "
                                 f"“mineral enriched”, but their active ingredients also include organic UV filters, often called chemical filters, "
                                 f"such as homosalate, octocrylene, octinoxate or octisalate. To know whether a sunscreen "
                                 f"is mineral only, read the Active ingredients in the Drug Facts box: only zinc oxide "
                                 f"and titanium dioxide are mineral filters."),
        "legal_framing": ("Not a violation: no US rule defines “mineral” on a sunscreen label, and each of these "
                          "products contains zinc oxide or titanium dioxide. Every active ingredient is listed in the "
                          "Drug Facts box, as the law requires. The finding compares the front of the package with the "
                          "Drug Facts; it is not about any brand."),
        "numerator": len(mrows), "denominator": N, "population": POP,
        "ingredient_source": FDA_QA,
        "detail": {"formulas": mrows, "mixed_formulas": combo_forms, "name_only": name_only,
                   "discloses": sum(1 for x in mrows if x["discloses_chemical"]),
                   "reviewed_labels": len([s for s in mw if s in candidates]), "unreviewed": unreviewed},
        "caveat": CAVEAT, "site_source": src, "method": "claims/registry_stats.py (mineral wording)",
        "verified_date": snapshot})

    # Parabens
    PARABENS = [("propylparaben", r"(?<![A-Z])PROPYL ?PARABEN"), ("methylparaben", r"(?<![A-Z])METHYL ?PARABEN"),
                ("butylparaben", r"(?<![A-Z])BUTYL ?PARABEN"), ("ethylparaben", r"(?<![A-Z])ETHYL ?PARABEN"),
                ("isobutylparaben", r"(?<![A-Z])ISOBUTYL ?PARABEN")]
    pb_rows = []
    for r in forms:
        found = [n for n, pat in PARABENS if where_listed(r, pat)]
        if found:
            pb_rows.append({"title": r["title"], "url": r["dailymed_url"], "parabens": found,
                            "mineral": bool(r.get("is_mineral_only_actives"))})
    pb_per = collections.Counter(n for row in pb_rows for n in row["parabens"])
    claims.append({
        "id": "US-BABY-PARABENS", "status": "verified", "jurisdiction": "US",
        "ingredient_slugs": [], "finding": "parabens",
        "claim": f"{len(pb_rows)} of {N} baby/kids sunscreen formulations list at least one paraben.",
        "publishable_sentence": (f"{len(pb_rows)} of the {N} baby and kids sunscreen formulas listed in the FDA's DailyMed "
                                 f"label database list at least one paraben preservative: propylparaben in "
                                 f"{pb_per['propylparaben']}, methylparaben in {pb_per['methylparaben']}, butylparaben in "
                                 f"{pb_per['butylparaben']}, ethylparaben in {pb_per['ethylparaben']} and isobutylparaben in "
                                 f"{pb_per['isobutylparaben']}."),
        "legal_framing": ("Not a violation in the US: parabens are allowed in US sunscreens. In the EU, isobutylparaben is "
                          "banned from all cosmetics, and propylparaben and butylparaben are limited to 0.14% combined and "
                          "may not be used in leave-on products designed for the nappy area of children under three. "
                          "Labels do not state paraben percentages, so the 0.14% limit cannot be checked from them."),
        "numerator": len(pb_rows), "denominator": N, "population": POP,
        "ingredient_source": {"title": "Commission Regulation (EU) No 1004/2014 (propylparaben, butylparaben)",
                              "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R1004",
                              "checked": "2026-10-08"},
        "detail": {"per_paraben": [[n, pb_per[n]] for n, _ in PARABENS],
                   "mineral": [sum(1 for x in pb_rows if x["mineral"]), M],
                   "formulas": sorted(pb_rows, key=lambda x: (-len(x["parabens"]), x["title"]))},
        "caveat": CAVEAT, "site_source": src,
        "method": "claims/registry_stats.py (PARABENS)", "verified_date": snapshot})

    # Fragrance
    fr = [r for r in forms if where_listed(r, FRAGRANCE.pattern)]
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
                   "printed_only": sum(1 for r in fr if where_listed(r, FRAGRANCE.pattern) == ["printed label"]),
                   "not_counted": "essential oils and other single scent ingredients; only fragrance, parfum or perfume"},
        "caveat": CAVEAT, "site_source": src,
        "method": "claims/registry_stats.py (FRAGRANCE)", "verified_date": snapshot})

    with open(LEDGER, encoding="utf-8") as f:
        ledger = json.load(f)
    ids = {c["id"] for c in claims}
    kept = [c for c in ledger["claims"] if c["id"] not in ids]
    # The morning's provisional counts are superseded by the reviewed list.
    for c in kept:
        if c["id"] == "US-BABY-MINERAL-BOOSTERS":
            c["status"], c["superseded_by"] = "superseded", "US-BABY-BOOSTERS"
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
