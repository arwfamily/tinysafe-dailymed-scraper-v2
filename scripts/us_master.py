#!/usr/bin/env python3
"""US sunscreen master: ONE record per label, everything downstream reads it.

    data/master/us_master.jsonl

Inputs (all in this repo):
  data/canonical/us_sunscreens.jsonl   this week's DailyMed collection
  data/views/inactive_union.jsonl      structured SPL table ∪ printed Drug Facts list
  data/verification/ledger.jsonl       label checks, keyed by (setid, spl_version)
  data/recalls/us_drug_recalls.jsonl   FDA drug recalls (scripts/recalls_fetch.py), optional
  data/reference/flags_v31.json        frozen v3.1 ingredient -> flag map (rules v3.2 start here)
  data/reference/sunnytime_v31_products.json  display names of the 6,544 v3.1 labels
  data/master/us_master.jsonl          last week's master (labels that left DailyMed stay, as discontinued)

Decisions this encodes (Angela, 2026-10-19):
  * scope        category == sunscreen; SPF makeup and lip balm are kept out (reason recorded)
  * discontinued a label that leaves DailyMed is kept with status "discontinued" and its last_seen
  * one label = one product; identical formulas under other labels are NOT merged
  * mineral      any label whose actives include zinc oxide or titanium dioxide, hybrids included;
                 filter_type says which: mineral_only | hybrid_mineral_primary |
                 hybrid_chemical_primary | hybrid_equal | hybrid_pct_unknown (main filter = larger
                 summed w/w % on the Drug Facts panel) | chemical_only | no_uv_filter
  * baby_kids    the product name says baby / infant / toddler / kids / children / junior ...;
                 any filter type
  * recalls      matched on setid or NDC = "matched"; on brand + product words only = "needs_review"

Usage: python3 scripts/us_master.py [--run-date YYYY-MM-DD]
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ledger as L  # noqa: E402
import sunnytime_rules as R  # noqa: E402
from inactive_union import _ACTIVE_SYN, is_active, key, same_display  # noqa: E402
from sunnytime_db import Engine, inactive_flags, no_preservative  # noqa: E402

CANON = os.path.join(ROOT, "data/canonical/us_sunscreens.jsonl")
UNION = os.path.join(ROOT, "data/views/inactive_union.jsonl")
RECALLS = os.path.join(ROOT, "data/recalls/us_drug_recalls.jsonl")
REF_FLAGS = os.path.join(ROOT, "data/reference/flags_v31.json")
REF_PRODUCTS = os.path.join(ROOT, "data/reference/sunnytime_v31_products.json")
MASTER = os.path.join(ROOT, "data/master/us_master.jsonl")

SCHEMA_VERSION = "1.0.0"
RULES_VERSION = "v3.2 · 2026-10-19"
THIN_MAX = 7
EVIDENCE_CAP = 4
MINERAL = ("ZINC OXIDE", "TITANIUM DIOXIDE")
EXCLUDED_REASON = {"makeup": "spf_makeup", "lip_balm": "spf_lip_balm", "diaper_cream": "diaper_cream",
                   "calamine": "calamine", "other": "not_a_sunscreen"}
BABY_KIDS = re.compile(r"(BAB(?:Y|IES)|\bINFANTS?\b|NEWBORN|TODDLER|\bB[EÉ]B[EÉ]S?\b|\bKIDS?\b|\bKID'?S\b|"
                       r"\bCHILD(?:REN)?(?:'S)?\b|\bJUNIOR\b|LITTLE ONES|\bNI[ÑN]OS\b|\bENFANTS?\b)", re.I)
SPRAY = re.compile(r"SPRAY|AEROSOL|\bPOWDER\b|\bMIST\b", re.I)     # "Spray150Ml" counts; the brand "Mistine" does not
WATER_RES = re.compile(r"\b(WATER|SWEAT)[ -]?RESISTANT\b", re.I)
_PCT_NAME = re.compile(r"\s*\((?:[^()]*\b(?:OXIDE|DIOXIDE|AVOBENZONE|HOMOSALATE|OCTISALATE|OCTOCRYLENE|OCTINOXATE|"
                       r"OXYBENZONE|ENSULIZOLE|SUNSCREEN)\b[^()]*)\)", re.I)


def jl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]


def engine_from_reference(path=REF_FLAGS):
    """The v3.2 Engine, built from the frozen v3.1 map instead of the old db.json."""
    ref = json.load(open(path, encoding="utf-8"))
    names = list(ref["names"])
    idx = {n: i for i, n in enumerate(names)}
    by_flag = collections.defaultdict(list)
    for n, fs in ref["names"].items():
        for f in fs:
            by_flag[f].append(n)
    pseudo = {"v3": [[f, ns, ""] for f, ns in by_flag.items()],
              "i": [idx[n] for n, k in ref["freq"].items() for _ in range(k)]}
    return Engine({"names": names, "p": [pseudo]}), ref["meta"]


def display_name(c):
    """'NEUTROGENA ... SPF 30 (TITANIUM DIOXIDE, ZINC OXIDE) LOTION' -> 'Neutrogena ... SPF 30 Lotion'."""
    n = _PCT_NAME.sub("", c.get("product_name") or c.get("title") or "")
    n = re.sub(r"\s+", " ", n).strip()
    words = []
    for w in n.split(" "):
        if re.fullmatch(r"SPF\d*|UVA|UVB|PA\+*|[A-Z]?\d+[A-Z]*", w, re.I):
            words.append(w.upper() if w.upper().startswith(("SPF", "UVA", "UVB", "PA")) else w)
        else:
            words.append(w[:1].upper() + w[1:].lower())
    return " ".join(words)


def actives(c, legacy=None):
    if not c.get("active_ingredients") and legacy and legacy.get("z"):
        # the collector fell back to openFDA for this label and got no actives: use the v3.1 db's
        return [{"name": z[0].upper(), "unii": None, "percent": z[1], "percent_basis": "v3.1_db"} for z in legacy["z"]]
    out = []
    for a in c.get("active_ingredients") or []:
        out.append({"name": (a.get("name") or "").upper(), "unii": a.get("unii"), "percent": a.get("percent_ww"),
                    "percent_basis": a.get("percent_basis")})
    return out


# organic (chemical) UV filters under US and INCI names; the canonical uv_filters_* lists use US
# names only, while many labels declare INCI names ("ETHYLHEXYL SALICYLATE" = octisalate)
UV_ORGANIC = re.compile(r"AVOBENZONE|OXYBENZONE|OCTINOXATE|OCTISALATE|HOMOSALATE|OCTOCRYLENE|ENSULIZOLE|ECAMSULE|"
                        r"MERADIMATE|SULISOBENZONE|DIOXYBENZONE|PADIMATE|CINOXATE|TROLAMINE SALICYLATE|BEMOTRIZINOL|"
                        r"BISOCTRIZOLE|ETHYLHEXYL SALICYLATE|OCTYL SALICYLATE|BUTYL METHOXYDIBENZOYLMETHANE|"
                        r"BENZOPHENONE-?[348]\b|METHOXYCINNAMATE|ETHYLHEXYL TRIAZONE|DIETHYLAMINO HYDROXYBENZOYL|"
                        r"BIS-?ETHYLHEXYLOXYPHENOL|METHYLENE BIS-?BENZOTRIAZOLYL|DROMETRIZOLE|TEREPHTHALYLIDENE|"
                        r"PHENYLBENZIMIDAZOLE|MENTHYL ANTHRANILATE|ISOAMYL P-METHOXYCINNAMATE|POLYSILICONE-15|"
                        r"\bPABA\b|AMINOBENZOIC ACID|DIGALLOYL TRIOLEATE|BENZYLIDENE CAMPHOR|ISCOTRIZINOL|"
                        r"AMILOXATE|HOMOMENTHYL")


def is_mineral_active(name):
    return any(m in name for m in MINERAL)


def filter_split(c, acts):
    mf = [a["name"] for a in acts if is_mineral_active(a["name"])]
    of = [a["name"] for a in acts if not is_mineral_active(a["name"]) and UV_ORGANIC.search(a["name"])]
    for x in c.get("uv_filters_organic") or []:          # anything the collector recognised that the regex missed
        for a in acts:
            if x.upper() in a["name"] and a["name"] not in of and not is_mineral_active(a["name"]):
                of.append(a["name"])

    def pct(names):
        vals = [a["percent"] for a in acts if a["name"] in names]
        return (None if any(v is None for v in vals) else round(sum(vals), 4)) if vals else 0.0
    mp, cp = pct(mf), pct(of)
    if mf and not of:
        ft = "mineral_only"
    elif of and not mf:
        ft = "chemical_only"
    elif not mf and not of:
        ft = "no_uv_filter"
    elif mp is None or cp is None:
        ft = "hybrid_pct_unknown"
    elif mp > cp:
        ft = "hybrid_mineral_primary"
    elif cp > mp:
        ft = "hybrid_chemical_primary"
    else:
        ft = "hybrid_equal"
    return ft, mp, cp, of


def mineral_type(acts):
    z = any("ZINC OXIDE" in a["name"] for a in acts)
    t = any("TITANIUM DIOXIDE" in a["name"] for a in acts)
    return "zinc_titanium" if z and t else "zinc" if z else "titanium" if t else "none"


# ---------------------------------------------------------------- recalls
_NDC = re.compile(r"\b(\d{4,5})-(\d{3,4})(?:-\d{1,2})?\b")
_HAZ = [("benzene", re.compile(r"benzene", re.I)),
        ("contamination", re.compile(r"contamina|microb|bacteri|mold|fung|pseudomonas|burkholderia", re.I))]
_STOPW = {"SUNSCREEN", "SPF", "BROAD", "SPECTRUM", "LOTION", "CREAM", "SPRAY", "STICK", "MINERAL", "INC", "LLC",
          "THE", "AND", "WITH", "FOR", "OZ", "ML", "ZINC", "OXIDE", "TITANIUM", "DIOXIDE", "WATER", "RESISTANT",
          "MINUTES", "FACE", "BODY", "KIDS", "BABY", "SENSITIVE", "SKIN", "COMPANY", "CORP", "CORPORATION"}


_STOPW |= {"NET", "BOTTLE", "BOTTLES", "TUBE", "TUBES", "CAN", "CANS", "UPC", "NDC", "PACKAGED", "DELIVER", "FLOZ",
           "LOT", "EXP", "DISTRIBUTED", "MANUFACTURED", "MADE", "PACK", "CARTON", "JAR", "PUMP", "SIZE", "TRAVEL",
           "COUNT", "PER", "UNITS", "LABEL", "LABELED", "PRODUCT", "PRODUCTS", "USA", "INC", "LTD", "CO",
           "AVOBENZONE", "HOMOSALATE", "OCTISALATE", "OCTOCRYLENE", "OCTINOXATE", "OXYBENZONE", "PROTECTION",
           "PROTECT", "PLUS", "DAILY", "ULTRA", "MOISTURIZER", "MOISTURIZING", "SUN", "SUNBLOCK"}


def _toks(s):
    return {w for w in re.sub(r"[^A-Z]+", " ", (s or "").upper()).split() if len(w) >= 3 and w not in _STOPW}


def _hazards(text):
    hs = [h for h, rx in _HAZ if rx.search(text or "")]
    return hs or ["other"]


class RecallIndex:
    def __init__(self, recalls):
        self.by_setid = collections.defaultdict(list)
        self.by_ndc = collections.defaultdict(list)
        self.all = recalls
        for r in recalls:
            for s in r.get("spl_set_id") or []:
                self.by_setid[s].append(r)
            ndcs = set(r.get("product_ndc") or [])
            for m in _NDC.finditer((r.get("product_description") or "") + " " + (r.get("code_info") or "")):
                ndcs.add(f"{m.group(1)}-{m.group(2)}")
            for n in ndcs:
                self.by_ndc[n].append(r)
            r["_toks"] = _toks(r.get("product_description")) | _toks(r.get("recalling_firm"))
            r["_firm"] = _toks(r.get("recalling_firm")) | _toks(r.get("brand"))

    def match(self, c, name):
        found = {}
        for r in self.by_setid.get(c["setid"], []):
            found[r["recall_number"]] = ("matched", "setid", r)
        for n in [c.get("ndc_product")] + list(c.get("ndc_products") or []):
            for r in self.by_ndc.get(n or "", []):
                found.setdefault(r["recall_number"], ("matched", "ndc", r))
        firm = _toks(c.get("labeler")) | _toks(c.get("labeler_from_title"))
        words = _toks(name) - firm
        for r in self.all:
            if r["recall_number"] in found or not (firm & r["_firm"]):
                continue
            # same firm AND the recalled product's own words are (mostly) this label's words
            rw = r["_toks"] - r["_firm"] - firm
            hit = words & rw
            if len(hit) >= 3 and len(hit) >= 0.6 * min(len(rw), len(words)):
                found[r["recall_number"]] = ("needs_review", "brand_and_name", r)
        out = []
        for rid, (st, how, r) in sorted(found.items()):
            out.append({"recall_number": rid, "status": st, "matched_on": how, "date": r.get("recall_initiation_date"),
                        "classification": r.get("classification"), "reason": (r.get("reason_for_recall") or "")[:300],
                        "hazards": _hazards(r.get("reason_for_recall")), "recall_status": r.get("status"),
                        "url": r.get("url")})
        return out


# ---------------------------------------------------------------- inactives + flags
def akeys_of(acts):
    ks = set()
    for a in acts:
        k = key(a["name"])
        ks.add(k)
        ks |= _ACTIVE_SYN.get(k, set())
    return ks


def inactives(c, u, chk, acts):
    ak = akeys_of(acts)
    if u and chk and chk.get("inactives") and chk["status"] in L.APPLIES:
        printed = list(chk["inactives"])
        extra = [x for x in u["struct"] if not any(same_display(x, t) for t in printed) and len(x.split()) <= 12]
        u = dict(u, i_union=printed + extra, i_text_n=len(printed),
                 i_src="image" if "image" in chk.get("source", "") else "both")
    names = [n for n in (u["i_union"] if u else []) if not is_active(n, ak)]
    struct = [n for n in (u["struct"] if u else []) if not is_active(n, ak)]
    return names, struct, u


def thin_reason(u, chk):
    st = (chk or {}).get("status")
    if st == "no_list_on_label_images":
        return "no_printed_list"
    if st == "image_unreadable":
        return "label_image_unreadable"
    if not u or u["i_text_n"] == 0:
        return "no_printed_list"
    if u["i_union_n"] <= 3 and any(R.WATER.search(x.upper()) for x in u["i_union"]):
        return "label_prints_too_little"
    return "short_list"


def flags(eng, meta, shown, struct, acts, organic, c, thin, treason):
    fl = collections.OrderedDict()

    def add(f, ev):
        if f not in fl:
            fl[f] = []
        fl[f] = list(dict.fromkeys(fl[f] + ev))[:EVIDENCE_CAP]
    for f, ev in inactive_flags(eng, list(dict.fromkeys(shown + struct))).items():
        add(f, ev)
    # non-UV actives (skin protectants such as dimethicone) read like inactives
    # every non-mineral active is read like an inactive too (dimethicone as a skin protectant gives
    # "silicone", drometrizole trisiloxane too); a declared UV active is never a HIDDEN booster
    non_min = [a["name"] for a in acts if not is_mineral_active(a["name"])]
    for f, ev in inactive_flags(eng, non_min).items():
        if f in ("hidden_uv_booster", "chemical_filter_in_inactives") and all(x in organic for x in ev):
            continue
        add(f, ev)
    if organic:
        add("chemical_filter_active", list(organic))
    form = " ".join([c.get("dosage_form") or "", c.get("title") or "", c.get("product_name") or ""])
    if SPRAY.search(form):
        add("spray_powder", [])
        if "talc" in fl:
            add("talc_inhalable", fl["talc"])
    wr = (c.get("label_flags") or {}).get("water_resistant_minutes")
    if wr or WATER_RES.search(form):
        add("water_resistant", [])
    if no_preservative(list(dict.fromkeys(shown + struct))) and not (thin and treason != "short_list"):
        add("no_preservative_water_base", [])
    order = list(meta)
    return [[f, fl[f], meta.get(f, {}).get("l", f)] for f in sorted(fl, key=lambda f: order.index(f) if f in order else 999)]


# ---------------------------------------------------------------- build
def build(run_date):
    canon = jl(CANON)
    union = {r["setid"]: r for r in jl(UNION)}
    led = L.load()
    recalls = RecallIndex(jl(RECALLS))
    legacy = json.load(open(REF_PRODUCTS, encoding="utf-8")) if os.path.exists(REF_PRODUCTS) else {}
    prev = {r["setid"]: r for r in jl(MASTER)}
    eng, meta = engine_from_reference()
    out = {}
    for c in canon:
        sid = c["setid"]
        ver = c.get("spl_version")
        chk = L.current(led, sid, ver) if ver is not None else (
            max((led.get(sid) or {}).values(), key=lambda r: r.get("checked", ""), default=None))
        acts = actives(c, legacy.get(sid))
        ft, mp, cp, organic = filter_split(c, acts)
        in_scope = c.get("category") == "sunscreen"
        name = (legacy.get(sid) or {}).get("n") or display_name(c)
        u = union.get(sid)
        shown, struct, u2 = inactives(c, u, chk, acts)
        thin = len(shown) <= THIN_MAX
        treason = thin_reason(u2, chk) if thin else None
        rec = {
            "setid": sid, "spl_version": ver, "status": "active", "first_seen": c.get("first_seen"),
            "last_seen": c.get("last_seen"), "in_scope": in_scope,
            "excluded_reason": None if in_scope else EXCLUDED_REASON.get(c.get("category"), c.get("category")),
            "category": c.get("category"), "name": name, "title": c.get("title"),
            "brand": (legacy.get(sid) or {}).get("b") or c.get("labeler"), "labeler": c.get("labeler"),
            "spf": c.get("spf"), "dosage_form": c.get("dosage_form"), "ndc_product": c.get("ndc_product"),
            "dailymed_url": c.get("dailymed_url"), "effective_date": c.get("effective_date"),
            "actives": acts, "mineral_type": mineral_type(acts), "filter_type": ft,
            "mineral_pct": mp, "chemical_pct": cp,
            "is_mineral": ft not in ("chemical_only", "no_uv_filter"),
            "is_baby_kids": bool(BABY_KIDS.search(" ".join([c.get("product_name") or "", c.get("title") or ""]))),
            "inactives": shown, "inactive_source": (u2 or {}).get("i_src", "structured"),
            "inactives_filed_n": (u2 or {}).get("i_struct_n", 0), "inactives_printed_n": (u2 or {}).get("i_text_n", 0),
            "label_check": (chk or {}).get("status"), "label_check_date": (chk or {}).get("checked"),
            "label_check_stale": bool(L.stale(led, sid, ver)) and chk is None,
            "thin": thin, "thin_reason": treason,
            "flags": flags(eng, meta, shown, struct, acts, organic, c, thin, treason),
            "recalls": recalls.match(c, c.get("product_name") or name) if recalls.all else [],
            "recall_checked": bool(recalls.all),
            "formulation_hash": c.get("formulation_hash"),
        }
        if not recalls.all and (legacy.get(sid) or {}).get("r"):
            rec["recalls"] = [{"recall_number": None, "status": "matched", "matched_on": "v3.1_db",
                               "hazards": legacy[sid]["r"]}]
        out[sid] = rec
    # labels that left DailyMed: keep them, marked discontinued
    for sid, r in prev.items():
        if sid not in out:
            out[sid] = dict(r, status="discontinued", discontinued_on=r.get("discontinued_on") or run_date)
    seedp = os.path.join(ROOT, "data/reference/discontinued_seed_2026-10-19.json")
    seed = json.load(open(seedp, encoding="utf-8"))["labels"] if os.path.exists(seedp) else {}
    for sid, lp in legacy.items():
        if sid not in out:
            out[sid] = dict(seed.get(sid) or {"thin": False})
            out[sid].update({"setid": sid, "status": "discontinued", "discontinued_on": "2026-10-19", "in_scope": True,
                        "excluded_reason": None, "name": lp["n"], "brand": lp["b"], "spf": lp["s"],
                        "mineral_type": lp["m"], "actives": [{"name": z[0], "percent": z[1]} for z in lp["z"]],
                        "filter_type": None, "is_mineral": lp["m"] != "none",
                        "recalls": [{"recall_number": None, "status": "matched", "matched_on": "v3.1_db",
                                     "hazards": lp["r"]}] if lp.get("r") else [],
                        "note": "in the 2026-10-19 site db, no longer on DailyMed; last verified record kept"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    out = build(a.run_date)
    os.makedirs(os.path.dirname(MASTER), exist_ok=True)
    with open(MASTER, "w", encoding="utf-8") as f:
        for sid in sorted(out):
            f.write(json.dumps(out[sid], ensure_ascii=False, separators=(",", ":")) + "\n")
    c = collections.Counter()
    for r in out.values():
        if r.get("in_scope"):
            c["in_scope"] += 1
            c["status:" + r["status"]] += 1
            c["mineral"] += bool(r.get("is_mineral"))
            c["baby_kids"] += bool(r.get("is_baby_kids"))
    print(f"wrote {len(out)} labels -> {MASTER}", dict(c))


if __name__ == "__main__":
    main()
