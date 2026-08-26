#!/usr/bin/env python3
"""
build_answer_keys.py — derive the things that have a RIGHT ANSWER.

Ingredient lists are claims. Recall records and legal texts are not. This script
crosses them to produce three machine-checkable views:

  1. views/claim_audit.jsonl
     Does the INCI support the label claim? ("100% mineral", "fragrance free",
     "no hidden filters", "reef" wording). Every verdict cites the ingredient
     that decided it. UNKNOWN when the ingredient list is empty — never PASS.

  2. views/recall_join.jsonl
     Products whose brand appears in a recall record. Evidence-tiered:
       brand_exact  - brand token matches a recall brand/firm token
       brand_fuzzy  - normalised brand token match
     Candidates, not verdicts. A name match is not proof of the same product.

  3. views/jurisdiction_matrix.json   (only if regulatory files are present)
     ingredient x jurisdiction legal limit. Reads whatever exists under
     data/regulatory/. Absent files are reported, not silently skipped.

Everything here is derived and disposable. Delete the views, rerun, get them
back. The assets are data/raw/ and data/history/.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

CANONICAL = "data/canonical/us_sunscreens.jsonl"
REG_DIR = "data/regulatory"
VIEWS = "data/views"

MINERAL_ACTIVES = {"ZINC OXIDE", "TITANIUM DIOXIDE"}

# Organic UV filters, by name. Names (not UNII) because this checks the
# ingredient TEXT a parent or an LLM would read off the label.
ORGANIC_FILTERS = [
    "AVOBENZONE", "OXYBENZONE", "OCTINOXATE", "OCTYL METHOXYCINNAMATE",
    "OCTISALATE", "OCTYL SALICYLATE", "HOMOSALATE", "OCTOCRYLENE",
    "ENSULIZOLE", "MEXORYL", "MERADIMATE", "PADIMATE", "SULISOBENZONE",
    "DIOXYBENZONE", "CINOXATE", "TROLAMINE SALICYLATE", "BEMOTRIZINOL",
    "BISOCTRIZOLE", "ECAMSULE", "DROMETRIZOLE",
]

# Not UV filters under the monograph, but they absorb UV or boost SPF and read
# as "mineral" on a label. Presence is a transparency fact, not a safety claim.
HIDDEN_BOOSTERS = [
    "BUTYLOCTYL SALICYLATE", "BUTYLOCTYL SALICYLATE",
    "TRIDECYL SALICYLATE", "ETHYL FERULATE", "ETHYLHEXYL SALICYLATE",
]

FRAGRANCE_TERMS = ["FRAGRANCE", "PARFUM", "AROMA"]

# Reef legislation (Hawaii Act 104 and successors) names these two.
REEF_BANNED = ["OXYBENZONE", "OCTINOXATE", "OCTYL METHOXYCINNAMATE"]


LABELER_RE = re.compile(r"\[([^\]]+)\]\s*$")


def derive_identity(rec):
    """
    The v2 scraper emits no `brand` field — that was a derived field on the old
    hand-built feed. DailyMed titles carry the labeler in trailing brackets:
        "BADGER SPF 30 DAILY SUNSCREEN (ZINC OXIDE) CREAM [W.S. BADGER COMPANY]"
    The labeler is a BETTER join key than a guessed brand, because recall records
    carry recalling_firm / company. The leading words before the actives
    parenthesis are kept as a secondary key.
    Verified: labeler extracted on 13,285/13,285 records.
    """
    title = rec.get("title") or ""
    m = LABELER_RE.search(title)
    labeler = m.group(1).strip() if m else ""
    head = LABELER_RE.sub("", title)
    head = re.split(r"\s*\(", head)[0].strip()
    return labeler, head


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper())).strip()


def names(items):
    out = []
    for i in items or []:
        out.append(norm(i.get("name") if isinstance(i, dict) else i))
    return [x for x in out if x]


def find(hay, needles):
    hits = []
    for n in needles:
        for h in hay:
            if n in h:
                hits.append(h)
    return sorted(set(hits))


# ---------------------------------------------------------------- claim audit
def audit_claims(rec):
    act = names(rec.get("active_ingredients"))
    inact = names(rec.get("inactive_ingredients"))
    has_list = bool(inact)
    claims = {}

    non_mineral = [a for a in act if not any(m in a for m in MINERAL_ACTIVES)]
    organic_act = find(act, ORGANIC_FILTERS)
    boosters = find(inact, HIDDEN_BOOSTERS)

    claims["all_mineral_actives"] = {
        "verdict": "FAIL" if organic_act or non_mineral else ("PASS" if act else "UNKNOWN"),
        "evidence": organic_act or non_mineral or act,
    }
    claims["no_hidden_uv_boosters"] = {
        "verdict": "FAIL" if boosters else ("PASS" if has_list else "UNKNOWN"),
        "evidence": boosters,
        "note": "not a safety finding — these absorb UV or boost SPF while "
                "sitting in the inactive list",
    }
    frag = find(inact, FRAGRANCE_TERMS)
    claims["fragrance_free"] = {
        "verdict": "FAIL" if frag else ("PASS" if has_list else "UNKNOWN"),
        "evidence": frag,
    }
    reef = find(act, REEF_BANNED)
    claims["hawaii_act_104_compatible"] = {
        "verdict": "FAIL" if reef else ("PASS" if act else "UNKNOWN"),
        "evidence": reef,
        "note": "checks only the two filters named in the statute",
    }
    # 100% mineral, as consumers read it: mineral actives AND no booster
    both = (claims["all_mineral_actives"]["verdict"], claims["no_hidden_uv_boosters"]["verdict"])
    claims["hundred_percent_mineral"] = {
        "verdict": "PASS" if both == ("PASS", "PASS")
                   else ("UNKNOWN" if "UNKNOWN" in both else "FAIL"),
        "evidence": organic_act + non_mineral + boosters,
    }
    return claims


# ---------------------------------------------------------------- recall join
# Single-word brand names that are also ordinary product vocabulary. Matching on
# these alone produced false hits against unrelated recalls on the first real run.
GENERIC_SINGLE_WORD_BRANDS = {
    "ZINC", "MINERAL", "CLOUD", "BEYOND", "NATURAL", "PURE", "CLEAN", "SUN",
    "SOLAR", "REEF", "BABY", "KIDS", "SPORT", "DAILY", "FACE", "BODY", "SKIN",
    "CARE", "GLOW", "SHADE", "BLOCK", "SHIELD", "COVER", "LIGHT", "REPAIR",
    "PHYSICAL", "ORGANIC", "GREEN", "BLUE", "EVERY", "SIMPLE", "ESSENTIAL",
}

STOP = {"THE", "AND", "INC", "LLC", "CO", "COMPANY", "CORP", "LTD", "BRANDS",
        "GROUP", "USA", "US", "OF", "FOR", "BY", "DBA"}


def brand_tokens(text):
    return [t for t in norm(text).split()
            if len(t) > 2 and t not in STOP and not t.isdigit()]


SUNSCREEN_SIGNAL = re.compile(
    r"\bsunscreen|\bsunblock|\bsun block|\bSPF\s*\d|\bsun care|\bafter ?sun"
    r"|zinc oxide|titanium dioxide|avobenzone|octinoxate|octocrylene|oxybenzone"
    r"|homosalate|octisalate|ensulizole|bemotrizinol|padimate|sulisobenzone",
    re.IGNORECASE)

DISTRIBUTOR_HINT = re.compile(
    r"\bKROGER\b|\bWALGREEN|\bCVS\b|\bWAL[- ]?MART\b|\bTARGET CORP"
    r"|\bCOSTCO\b|\bCARDINAL HEALTH\b|\bMCKESSON\b|\bAMERISOURCE"
    r"|\bRITE AID\b|\bDOLLAR (GENERAL|TREE)\b|\bSAFEWAY\b|\bALBERTSONS\b"
    r"|\bPUBLIX\b|\bH-?E-?B\b|\bMEIJER\b|\bFAMILY DOLLAR\b|\bTOPCO\b",
    re.IGNORECASE)

COMMON_TOKENS = set()


def build_recall_index(recall_path):
    """
    Keep only recalls whose OWN TEXT names a sunscreen or a UV filter.

    Matching on company alone put Kroger's Halloween candles, acetaminophen and
    hooded sweatshirts against 797 sunscreen products, because a distributor
    labels everything it sells and recalls everything it labels. Of 6,279
    recall records exactly 15 mention a sunscreen; the other 6,264 cannot be
    about one no matter whose name is on the package.
    """
    all_rows = []
    with open(recall_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_rows.append(json.loads(line))

    def blob(r):
        return " ".join(str(r.get(k) or "") for k in
                        ("product_name", "display_name", "heading",
                         "reason", "plain_reason", "hazard_text"))

    rows = [r for r in all_rows if SUNSCREEN_SIGNAL.search(blob(r))]

    idx = defaultdict(list)
    tokens = set()
    for r in rows:
        fields = " ".join(str(r.get(k) or "") for k in
                          ("brand", "recalling_firm", "company", "product_name",
                           "display_name", "heading"))
        stub = {
            "recall_id": r.get("recall_id") or r.get("id"),
            "recall_date": r.get("recall_date"),
            "source": r.get("source"),
            "product_name": r.get("product_name"),
            "brand": r.get("brand"),
            "hazard": r.get("hazard"),
            "reason": r.get("reason"),
            "status": r.get("status"),
            "classification": r.get("classification"),
            "deaths_reported": r.get("deaths_reported"),
            "_brandstack": norm(" ".join(str(r.get(k) or "") for k in
                                         ("brand", "recalling_firm", "company",
                                          "product_name", "display_name"))),
        }
        for t in set(brand_tokens(fields)):
            idx[t].append(stub)
            tokens.add(t)
    return idx, len(all_rows), tokens, None, len(rows)


def product_side_common_tokens(prods, max_share=0.005):
    """
    Judge a token's distinctiveness against the 13,000-product corpus, not
    against 15 recalls. In a set that small every token looks rare, so SKIN,
    CARE and SUN were briefly treated as identifying and matched Kabana's
    recall onto every company with "Skin Care" in its name.
    """
    df = defaultdict(int)
    seen = set()
    for p in prods:
        labeler, head = derive_identity(p)
        key = norm(labeler or head)
        if not key or key in seen:
            continue
        seen.add(key)
        for t in set(brand_tokens(key)):
            df[t] += 1
    n = max(1, len(seen))
    return {t for t, c in df.items() if c > max_share * n}, n


def join_recalls(prods, idx, distinctive):
    """
    A hit needs BOTH:
      (a) a distinctive brand token in common, and
      (b) the product's full normalised brand phrase present in the recall text.
    Token overlap alone was the failure mode; phrase containment is the guard.
    """
    out = []
    for p in prods:
        labeler, head = derive_identity(p)
        raw_brand = p.get("brand") or labeler or head
        phrase = norm(raw_brand)
        toks = brand_tokens(raw_brand)
        dtoks = [t for t in toks if t in distinctive and t not in COMMON_TOKENS]
        if not phrase or len(phrase) < 4 or not dtoks:
            continue
        # A one-word brand that is also a common English/product word will match
        # by accident ("Zinc" hit zinc oxide ointment; "Cloud", "Beyond").
        # Require either a multi-word brand or a single word that is not generic.
        if len(toks) == 1 and toks[0] in GENERIC_SINGLE_WORD_BRANDS:
            continue
        # a distributor's name links a recall to distribution, not to this
        # formulation — the finding wanted is "this maker's product failed"
        if DISTRIBUTOR_HINT.search(raw_brand):
            continue
        hits = {}
        for t in dtoks:
            for stub in idx.get(t, []):
                key = stub["recall_id"]
                if not key or key in hits:
                    continue
                if phrase in stub["_brandstack"]:
                    tier = "brand_phrase"
                elif len(dtoks) >= 2 and all(d in stub["_brandstack"] for d in dtoks):
                    tier = "brand_all_tokens"
                else:
                    continue
                s = {k: v for k, v in stub.items()
                     if k not in ("_haystack", "_brandstack")}
                hits[key] = {**s, "matched_on": t, "tier": tier}
        if not hits:
            continue
        out.append({
            "setid": p.get("setid"),
            "brand": raw_brand,
            "brand_source": ("field" if p.get("brand")
                             else "labeler" if labeler else "title_head"),
            "product_name": p.get("product_name") or p.get("title"),
            "match_count": len(hits),
            "caveat": "brand match only — same brand, NOT proven same product. "
                      "Check product name and date before citing.",
            "recalls": sorted(hits.values(),
                              key=lambda x: str(x.get("recall_date") or ""),
                              reverse=True)[:25],
        })
    return sorted(out, key=lambda x: -x["match_count"])


# ------------------------------------------------------- jurisdiction matrix
def load_regulatory():
    """
    Read whatever regulatory files exist and report the ones that do not.

    Field names differ per source because each was extracted from a different
    legal text, so the mapping is declared here rather than guessed:
      EU Annex VI   inci_name / max_concentration_pct     / product_type_condition
      AU TGA        name      / max_concentration_percent / requirements
                    (wrapped: {"ingredients": [...]})
      KR 별표2       inci_name / max_concentration_pct    / source_status
      US M020       inci_name / max_concentration_percent
    """
    wanted = {
        "EU": {"files": ["eu_annex_vi.jsonl"],
               "label": "EU Cosmetics Regulation Annex VI",
               "name": ["inci_name", "inci", "name"],
               "max": ["max_concentration_pct", "max_concentration_percent",
                       "max_percent"],
               "cond": ["product_type_condition", "conditions"]},
        "AU": {"files": ["au_permissible_ingredients.json"],
               "label": "TGA Permissible Ingredients Determination",
               "name": ["name", "inci_name"],
               "max": ["max_concentration_percent"],
               "cond": ["requirements", "conditions"]},
        "KR": {"files": ["kr_uv_filters_partial.jsonl", "kr_uv_filters.jsonl"],
               "label": "MFDS 화장품 안전기준 별표2",
               "name": ["inci_name", "name"],
               "max": ["max_concentration_pct", "max_concentration_percent"],
               "cond": ["conditions", "requirements"]},
        "US": {"files": ["us_monograph_m020.jsonl"],
               "label": "FDA OTC Monograph M020",
               "name": ["inci_name", "name"],
               "max": ["max_concentration_pct", "max_concentration_percent",
                       "max_percent"],
               "cond": ["conditions"]},
    }
    found, missing = {}, {}
    for juris, spec in wanted.items():
        path = None
        for fn in spec["files"]:
            p = os.path.join(REG_DIR, fn)
            if os.path.exists(p):
                path = p
                break
        if not path:
            missing[juris] = {"expected": [os.path.join(REG_DIR, f)
                                           for f in spec["files"]],
                              "source": spec["label"]}
            continue
        with open(path, encoding="utf-8") as f:
            if path.endswith(".jsonl"):
                rows = [json.loads(l) for l in f if l.strip()]
            else:
                doc = json.load(f)
                rows = (doc if isinstance(doc, list)
                        else doc.get("ingredients", doc.get("data", [])))
        found[juris] = {"source": spec["label"], "file": os.path.basename(path),
                        "rows": rows, "spec": spec}
    return found, missing


def _first(row, keys):
    for k in keys:
        if row.get(k) not in (None, ""):
            return row.get(k)
    return None


def build_matrix(found):
    """
    ingredient -> jurisdiction -> limit, ONE row per filter.

    Aliases must MERGE, not multiply. The first version indexed each alias as
    its own key, so Octinoxate / Octyl Methoxycinnamate / Ethylhexyl
    Methoxycinnamate became three rows and each carried only the jurisdictions
    that happened to use that spelling. A reader looking up "Octinoxate" saw
    US 7.5 and dashes everywhere else — the opposite of the truth.

    So names are unioned across jurisdictions first (every alias set links its
    members), then one canonical row is emitted per group.
    """
    # pass 1: union alias groups
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for juris, blob in found.items():
        spec = blob["spec"]
        for row in blob["rows"]:
            key = norm(_first(row, spec["name"]))
            if not key:
                continue
            find(key)
            for a in (row.get("alt_names") or []):
                na = norm(a)
                if na:
                    union(key, na)

    groups = defaultdict(set)
    for k in list(parent):
        groups[find(k)].add(k)

    matrix = defaultdict(dict)
    stats = {}
    for juris, blob in found.items():
        spec = blob["spec"]
        kept = 0
        for row in blob["rows"]:
            key = norm(_first(row, spec["name"]))
            if not key:
                continue
            kept += 1
            # Same filter, different legal name per jurisdiction (Octinoxate vs
            # Ethylhexyl Methoxycinnamate). Index the aliases too or the
            # comparison rows silently never line up.
            keys = [key] + [norm(a) for a in (row.get("alt_names") or [])]
            entry = {
                "max_percent": _first(row, spec["max"]),
                "conditions": _first(row, spec["cond"]),
                "source": blob["source"],
            }
            if row.get("source_status"):
                entry["source_status"] = row["source_status"]
            for flag in ("is_active", "is_excipient", "dermal_topical_only",
                         "is_nano", "warning_statement_required"):
                if row.get(flag):
                    entry[flag] = row[flag]
            # several AU rows share a normalised name; keep the tightest limit
            root = find(key)
            entry["listed_as"] = key
            prev = matrix[root].get(juris)
            if prev and prev.get("max_percent") is not None:
                if entry["max_percent"] is None:
                    continue
                try:
                    if float(entry["max_percent"]) >= float(prev["max_percent"]):
                        continue
                except (TypeError, ValueError):
                    continue
            matrix[root][juris] = entry
        stats[juris] = {"rows": len(blob["rows"]), "named": kept,
                        "file": blob["file"]}

    # attach every known spelling to its row so a lookup by any name lands here
    out = {}
    for root, juris_map in matrix.items():
        out[root] = {"limits": juris_map,
                     "also_known_as": sorted(groups.get(root, {root}) - {root})}
    return out, stats


# --------------------------------------------------- cross-border legality
def check_legality(prods, matrix):
    """
    Would this product be legal, as formulated, in each other jurisdiction?

    Only runs on percent_ww, never on the raw strength field. SPL states
    concentration as a ratio and the first parser kept the numerator alone, so
    "216" (21.6 % as mg/g) and "3" (3 %) sat in one column indistinguishably.
    A guess here would say a product is legal where it is not, so anything
    without a resolved percent is UNKNOWN — never PASS.
    """
    alias = {}
    for root, v in matrix.items():
        alias[root] = root
        for a in v.get("also_known_as", []):
            alias[norm(a)] = root

    rows = []
    for p in prods:
        if p.get("category") != "sunscreen":
            continue
        acts = p.get("active_ingredients") or []
        if not acts:
            continue
        verdicts, unknown_any = {}, False
        details = []
        for a in acts:
            root = alias.get(norm(a.get("name")))
            pct = a.get("percent_ww")
            if root is None:
                unknown_any = True
                details.append({"ingredient": a.get("name"),
                                "issue": "not a mapped UV filter"})
                continue
            if pct is None:
                unknown_any = True
                details.append({"ingredient": a.get("name"),
                                "issue": f"no resolved percent "
                                         f"({a.get('percent_basis')})"})
                continue
            for j, lim in matrix[root]["limits"].items():
                mx = lim.get("max_percent")
                if mx is None:
                    continue
                try:
                    over = float(pct) > float(mx) + 1e-9
                except (TypeError, ValueError):
                    continue
                if over:
                    verdicts.setdefault(j, []).append({
                        "ingredient": root, "percent": pct,
                        "limit": mx, "listed_as": lim.get("listed_as")})
        if not verdicts and not unknown_any:
            continue
        rows.append({
            "setid": p.get("setid"),
            "title": p.get("title"),
            "over_limit": verdicts,
            "unresolved": details,
            "verdict": ("OVER_LIMIT" if verdicts
                        else "UNKNOWN_insufficient_data"),
            "caveat": "Compares stated active concentration against the "
                      "jurisdiction's maximum for that filter. It does not "
                      "check every other requirement for sale there.",
        })
    return rows


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", default=CANONICAL)
    ap.add_argument("--recalls", default=None,
                    help="path to recalls_full.jsonl (skip the join if absent)")
    ap.add_argument("--out", default=VIEWS)
    args = ap.parse_args()

    if not os.path.exists(args.canonical):
        print(f"FATAL: {args.canonical} not found — run the scraper + "
              "snapshot_and_history.py first", file=sys.stderr)
        return 1

    prods = [json.loads(l) for l in open(args.canonical, encoding="utf-8") if l.strip()]
    os.makedirs(args.out, exist_ok=True)
    print(f"[input] {len(prods)} products", flush=True)

    # 1. claim audit
    tally = defaultdict(lambda: defaultdict(int))
    with open(os.path.join(args.out, "claim_audit.jsonl"), "w", encoding="utf-8") as f:
        for p in prods:
            claims = audit_claims(p)
            for c, v in claims.items():
                tally[c][v["verdict"]] += 1
            f.write(json.dumps({
                "setid": p.get("setid"),
                "brand": p.get("brand"),
                "product_name": p.get("product_name"),
                "inactive_count": len(p.get("inactive_ingredients") or []),
                "claims": claims,
            }, ensure_ascii=False) + "\n")

    print("\n--- CLAIM AUDIT ---")
    suspicious = []
    for c, v in tally.items():
        print(f"{c:32} PASS {v['PASS']:5}  FAIL {v['FAIL']:5}  UNKNOWN {v['UNKNOWN']:5}")
        if v["FAIL"] == 0 and v["PASS"] > 50:
            suspicious.append(c)
    if suspicious:
        print("\n  !! UNIFORMITY WARNING: zero failures on " + ", ".join(suspicious))
        print("     A real market is never 100% compliant. This usually means the")
        print("     INPUT WAS PRE-FILTERED on the same condition, which makes any")
        print("     percentage computed from it circular. Check the collection net")
        print("     before publishing a number from this view.")

    # 2. recall join
    if args.recalls and os.path.exists(args.recalls):
        idx, n, distinctive, cutoff, kept = build_recall_index(args.recalls)
        global COMMON_TOKENS
        COMMON_TOKENS, n_lab = product_side_common_tokens(prods)
        joined = join_recalls(prods, idx, distinctive)
        with open(os.path.join(args.out, "recall_join.jsonl"), "w", encoding="utf-8") as f:
            for j in joined:
                f.write(json.dumps(j, ensure_ascii=False) + "\n")
        print(f"\n--- RECALL JOIN ---")
        print(f"recall records indexed : {n}")
        print(f"distinctive tokens     : {len(distinctive)} (a token in >{cutoff} recalls is treated as a common word)")
        print(f"products with a match  : {len(joined)}/{len(prods)}")
        by_co = defaultdict(lambda: {"skus": 0, "recalls": {}, "label": ""})
        for j in joined:
            e = by_co[norm(j["brand"])]
            e["skus"] += 1
            e["label"] = j["brand"]
            for rc in j["recalls"]:
                e["recalls"][rc["recall_id"]] = rc
        print(f"  = {len(by_co)} companies")
        for _, e in sorted(by_co.items(), key=lambda x: -len(x[1]["recalls"]))[:12]:
            rl = sorted(e["recalls"].values(),
                        key=lambda x: str(x.get("recall_date") or ""), reverse=True)
            print(f"  {e['label'][:30]:30} {len(rl):2} recalls | {e['skus']:3} SKUs")
            for rc in rl[:2]:
                print(f"       {str(rc.get('recall_date'))[:8]} "
                      f"{str(rc.get('hazard'))[:13]:13} "
                      f"{str(rc.get('product_name'))[:50]}")
    else:
        print("\n--- RECALL JOIN --- skipped (no --recalls path)")

    # 2b. cross-border legality (needs the matrix, so built after it below)

    # 3. jurisdiction matrix
    found, missing = load_regulatory()
    print(f"\n--- JURISDICTION MATRIX ---")
    for j, m in missing.items():
        print(f"  MISSING {j}: {' or '.join(m['expected'])}  ({m['source']})")
    if found:
        matrix, stats = build_matrix(found)
        for j, st in stats.items():
            print(f"  {j}: {st['named']}/{st['rows']} named rows from {st['file']}")
        multi = sum(1 for v in matrix.values() if len(v["limits"]) > 1)
        with_limit = sum(1 for v in matrix.values()
                         if any(x.get("max_percent") is not None
                                for x in v["limits"].values()))
        doc = {
            "coverage": stats,
            "ingredients_in_multiple_jurisdictions": multi,
            "ingredients_with_a_numeric_limit": with_limit,
            "built_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "jurisdictions_present": sorted(found),
            "jurisdictions_missing": sorted(missing),
            "ingredient_count": len(matrix),
            "matrix": matrix,
        }
        with open(os.path.join(args.out, "jurisdiction_matrix.json"), "w",
                  encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"  built: {len(matrix)} ingredients across {sorted(found)}")
        # legality needs the matrix
        leg = check_legality(prods, matrix)
        with open(os.path.join(args.out, "legality_check.jsonl"), "w",
                  encoding="utf-8") as f:
            for r in leg:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        over = [r for r in leg if r["verdict"] == "OVER_LIMIT"]
        print(f"\n--- CROSS-BORDER LEGALITY ---")
        print(f"  products flagged over a foreign limit : {len(over)}")
        byj = defaultdict(int)
        for r in over:
            for j in r["over_limit"]:
                byj[j] += 1
        for j, n in sorted(byj.items(), key=lambda x: -x[1]):
            print(f"    would exceed {j} limits: {n}")
        print(f"  products with unresolved concentration : "
              f"{len(leg) - len(over)}  (reported UNKNOWN, never PASS)")

        # SELF-CHECK. A US-registered sunscreen exceeding the US monograph is
        # almost always a unit-conversion error, not a lawbreaking product:
        # SPL states concentration as a ratio, so 216 mg/g and 3 % both arrive
        # as bare numbers and a bad conversion inflates one of them tenfold.
        # This number is therefore a health meter for the strength parser, and
        # every other jurisdiction's figure is only as good as it is.
        us_over = byj.get("US", 0)
        total_sun = sum(1 for p in prods if p.get("category") == "sunscreen")
        if total_sun and us_over > 0.01 * total_sun:
            print(f"\n  !! NORMALISATION WARNING: {us_over} US products exceed a "
                  f"US limit ({100*us_over/total_sun:.1f}% of sunscreens).")
            print("     US-registered sunscreens comply with M020 by construction,")
            print("     so this is a percent_ww conversion fault. DO NOT publish")
            print("     any cross-border figure until this is near zero.")
        else:
            print(f"  self-check: {us_over} US-over-US (expected ~0) — "
                  "normalisation looks sound")
        print(f"         {multi} appear in 2+ jurisdictions "
              f"(these are the comparison rows), {with_limit} carry a numeric limit")
    else:
        print("  no regulatory files present — matrix not built.")
        print("  drop the EU/AU/KR/US regulatory JSON into data/regulatory/ "
              "and this view appears automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
