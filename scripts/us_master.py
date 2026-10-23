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
  * baby_kids    the product name says baby / infant / toddler / kids / children / junior ...
                 (glued brand words too: Thinkkids, Kidstick), or the label's front panel does
                 (the DailyMed name is often cut: "Banana Boat Lotion" for Banana Boat Kids); any filter type
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
import scope_rules as S  # noqa: E402
import sunnytime_rules as R  # noqa: E402
import printed_strengths as PS  # noqa: E402
import functools  # noqa: E402
from inactive_union import _ACTIVE_SYN, is_active, key  # noqa: E402
from inactive_union import same_display as _same_display  # noqa: E402


@functools.lru_cache(maxsize=2_000_000)
def same_display(a, b):
    # the same pairs recur across thousands of labels; difflib is the slow part
    return _same_display(a, b)
from sunnytime_db import Engine, inactive_flags, no_preservative  # noqa: E402

CANON = os.path.join(ROOT, "data/canonical/us_sunscreens.jsonl")
UNION = os.path.join(ROOT, "data/views/inactive_union.jsonl")
RECALLS = os.path.join(ROOT, "data/recalls/us_drug_recalls.jsonl")
REF_FLAGS = os.path.join(ROOT, "data/reference/flags_v31.json")
REF_PRODUCTS = os.path.join(ROOT, "data/reference/sunnytime_v31_products.json")
MASTER = os.path.join(ROOT, "data/master/us_master.jsonl")
CORRECTIONS = os.path.join(ROOT, "data/corrections/spl_label_errors.jsonl")
SCOPE_OVERRIDES = os.path.join(ROOT, "data/reference/scope_overrides.json")

SCHEMA_VERSION = "1.0.0"
RULES_VERSION = "v3.6 · 2026-10-23"
THIN_MAX = 7
EVIDENCE_CAP = 4
MINERAL = ("ZINC OXIDE", "TITANIUM DIOXIDE")
EXCLUDED_REASON = {"makeup": "spf_makeup", "lip_balm": "spf_lip_balm", "diaper_cream": "diaper_cream",
                   "calamine": "calamine", "other": "not_a_sunscreen"}
# glued brand words count too: Thinkkids, Kawakids, Kidstick, Safe4Kidz, Thinkbaby
BABY_KIDS = re.compile(r"(BAB(?:Y|IES)|\bINFANTS?\b|NEWBORN|TODDLER|\bB[EÉ]B[EÉ]S?\b|KID(?!NEY)|"
                       r"\bCHILD(?:REN)?(?:'S)?\b|\bJUNIOR\b|LITTLE ONES|\bNI[ÑN]OS\b|\bENFANTS?\b|\bTOTS?\b)", re.I)
# words the collector read on the label's front panel; "pediatrician tested" alone is not a kids product
FRONT_PANEL_BABY = {"BABY", "BABIES", "INFANT", "INFANTS", "NEWBORN", "TODDLER", "TODDLERS", "KID", "KIDS", "KIDZ",
                    "CHILD", "CHILDREN", "JUNIOR", "TOTS"}


def baby_kids(c):
    # the product part only: the [LABELER] bracket names companies (Wild Child Laboratories,
    # BabyFace LLC), not the product
    if BABY_KIDS.search(c.get("product_name") or S.product_part(c.get("title") or "")):
        return True, "name"
    fp = {w.upper() for w in ((c.get("label_flags") or {}).get("front_panel_baby_words") or [])}
    if fp & FRONT_PANEL_BABY:
        return True, "front_panel"
    return False, None
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


NOT_WW = ("w/w_from_mass_per_volume", "v/v")
ANALGESIC = {"TROLAMINE SALICYLATE", "MENTHOL", "CAMPHOR", "METHYL SALICYLATE", "LIDOCAINE", "LIDOCAINE HCL",
             "LIDOCAINE HYDROCHLORIDE", "CAPSAICIN", "HISTAMINE DIHYDROCHLORIDE"}
LABEL_CLAIMS_PATH = os.path.join(ROOT, "data/views/label_claims.jsonl")
LABEL_CLAIMS = ({json.loads(x)["setid"]: json.loads(x) for x in open(LABEL_CLAIMS_PATH, encoding="utf-8") if x.strip()}
                if os.path.exists(LABEL_CLAIMS_PATH) else {})
# labels whose text shows neither claim: the same tests on OCR of the label images
# (scripts/label_claims_ocr.py), used only for the same label version
_OCR_DIR = os.path.join(ROOT, "data/views/label_claims_ocr")
if os.path.isdir(_OCR_DIR):
    for _f in sorted(os.listdir(_OCR_DIR)):
        for _x in open(os.path.join(_OCR_DIR, _f), encoding="utf-8"):
            _d = json.loads(_x)
            _c = LABEL_CLAIMS.get(_d["setid"])
            if _d.get("error") or not _c or str(_c.get("spl_version")) != str(_d.get("spl_version")):
                continue
            if not (_c.get("broad_spectrum") or _c.get("aging_alert")):
                LABEL_CLAIMS[_d["setid"]] = dict(_c, broad_spectrum=_d["broad_spectrum"], aging_alert=_d["aging_alert"],
                                                 source="label_image_ocr")


US_MAX = {"AVOBENZONE": 3, "HOMOSALATE": 15, "OCTINOXATE": 7.5, "OCTISALATE": 5, "OCTOCRYLENE": 10, "OXYBENZONE": 6,
          "ENSULIZOLE": 4, "ZINC OXIDE": 25, "TITANIUM DIOXIDE": 25, "MERADIMATE": 5, "SULISOBENZONE": 10,
          "DIOXYBENZONE": 3, "CINOXATE": 3, "PADIMATE O": 8, "TROLAMINE SALICYLATE": 12, "BEMOTRIZINOL": 6}   # 21 CFR 352.10 / 2025 order
_ACTIVE_WORDS = re.compile(r"%|OXIDE|AVOBENZONE|HOMOSALATE|OCTI|OCTOCRYLENE|OXYBENZONE|ENSULIZOLE|SALICYLATE|MENTHOL|"
                           r"CAMPHOR|DIMETHICONE|ALLANTOIN|PETROLATUM|BEMOTRIZINOL", re.I)


def clean_name(n):
    """Drop parenthetical lists of actives from a product name ('... (Homosalate 5%, ...)')."""
    n0 = n or ""
    out, depth, start, buf = [], 0, 0, ""
    for i, ch in enumerate(n0):            # outermost bracket groups, nested ones included
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                grp = n0[start:i + 1]
                if not _ACTIVE_WORDS.search(grp):
                    out.append(grp)
                continue
        if depth == 0:
            out.append(ch)
    if depth:                              # unbalanced: leave the name as it was
        return re.sub(r"\s+", " ", n0).strip() or n
    return re.sub(r"\s+", " ", "".join(out)).strip() or n


def title_spf(*names):
    """The SPF printed in the product name or title ("SPF 50+", "SPF-30")."""
    for n in names:
        m = re.search(r"\bSPF\s*-?\s*(\d{1,3})", n or "", re.I)
        if m and 2 <= int(m.group(1)) <= 100:
            return int(m.group(1))
    return None


_DICT = {}


def _dict_job(name):
    """Main job of a label name in the ingredient dictionary (scripts/cosing)."""
    if not _DICT:
        sys.path.insert(0, os.path.join(HERE, "cosing"))
        import dictionary as DICT
        _DICT["names"] = sorted({n for line in open(UNION, encoding="utf-8") for n in
                                 (json.loads(line).get("i_union") or [])})
        _DICT["cache"] = DICT.build(_DICT["names"])          # one pass over every name
        _DICT["build"] = DICT.build
    if name not in _DICT["cache"]:
        _DICT["cache"].update(_DICT["build"]([name]))
    return (_DICT["cache"].get(name) or {}).get("job")


SOURCE_WORDS = {"SOYBEAN", "SOY", "EGG", "GLYCINE", "SOJA", "MAX"}
# flags about what an ingredient is made from (the same in any form of it)
SOURCE_FLAGS = {"soy", "egg", "milk", "wheat", "peanut", "tree_nut", "sesame", "fish_shellfish", "coconut", "shea",
                "oat", "asteraceae", "lanolin", "propolis_beeswax", "animal_derived", "botanical_count", "latex"}


def source_twins(printed, filed):
    """Filed names that are a printed ingredient plus its source: printed "Lecithin",
    filed "LECITHIN, SOYBEAN"; printed "Phospholipids", filed "EGG PHOSPHOLIPIDS". The
    filing says what the printed name does not (the soy or egg in it), so these still
    give their allergen flag when only the printed list is shown."""
    out = []
    for f in filed:
        F = set(re.findall(r"[A-Z]+", f.upper()))
        if not F & SOURCE_WORDS:
            continue
        for p in printed:
            P = set(re.findall(r"[A-Z]+", p.upper()))
            if P and P <= F and (F - P) <= SOURCE_WORDS:
                out.append((p, f))
                break
    return out


_FORMW = re.compile(r"\b(OIL|WATER|EXTRACT|BUTTER|WAX|JUICE|POWDER|ACID)\b")


def strict_twin(f, p):
    """Filed name f is printed name p under another name: related by same_display and
    of the same form (a rose OIL is not a rose flower WATER)."""
    if not (same_display(f, p) or same_display(p, f)):
        return False
    # and the same numbers: Polysilicone-11 is not Polysilicone-15, PEG-8 is not PEG-100
    nf, np_ = set(re.findall(r"\d+", f)), set(re.findall(r"\d+", p))
    if nf and np_ and nf != np_:
        return False
    return set(_FORMW.findall(f.upper())) == set(_FORMW.findall(p.upper()))


def flags(eng, meta, shown, struct, acts, organic, c, thin, treason, twins=()):
    fl = collections.OrderedDict()

    def cite(n, f):
        """The evidence names the ingredient as the printed label does, once: a filed
        name for a printed ingredient ("PROPYLENE GLYCOL" / "Propylene Glycol",
        "ALOE VERA LEAF" / "Aloe Barbadensis Leaf Extract") is cited by its printed name,
        but only by a printed name that itself gives the flag (a filed rose OIL is never
        cited as the printed rose flower WATER)."""
        if n in shown:
            return n
        return next((x for x in shown if same_display(n, x) and f in eng.flags(x)[0]), None) or next(
            (x for x in shown if strict_twin(n, x)), n)

    def add(f, ev, raw=False):
        if f not in fl:
            fl[f] = []
        out, seen = [], set()
        # raw: evidence that already says where it comes from ("Lecithin (filed with the FDA
        # as soybean lecithin)"), kept as written rather than mapped to a printed name
        for n in fl[f] + [x if raw else cite(x, f) for x in ev]:
            k = key(n) or n.upper()
            if k not in seen:
                seen.add(k)
                out.append(n)
        # every declared chemical active is listed; other flags cite up to EVIDENCE_CAP names
        fl[f] = out if f == "chemical_filter_active" else out[:EVIDENCE_CAP]
    for f, ev in inactive_flags(eng, list(dict.fromkeys(shown + struct))).items():
        add(f, ev)
    for p, f in twins:
        for g in eng.flags(f)[0] & SOURCE_FLAGS:
            if g not in fl:
                add(g, [p if g == "botanical_count" else f"{p} (filed with the FDA as {f.lower()})"], raw=True)
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
    # an aroma chemical the dictionary reads as added for scent (ethylene brassylate, ...)
    # that no fragrance pattern names: still a fragrance
    scent = [n for n in shown if _dict_job(n) == "fragrance"]
    if scent and not any(f in fl for f in ("fragrance", "essential_oil", "eu_fragrance_allergen")):
        add("fragrance", scent)
    # the title's [labeler] is the company, not the product ("[EMPACK SPRAYTECH]" on a lotion)
    form = " ".join([c.get("dosage_form") or "", re.sub(r"\[[^\]]*\]", " ", c.get("title") or ""),
                     re.sub(r"\[[^\]]*\]", " ", c.get("product_name") or "")])
    lc = LABEL_CLAIMS.get(c.get("setid"))
    # a roll-on is not sprayed, whatever form the filing chose; a stick or cream whose
    # filed text borrows spray directions is not a spray either (2026-10-22 label audit)
    U = form.upper()
    claim = bool(lc and (lc.get("spray") or lc.get("powder")))
    applied = bool(re.search(r"\bSTICK\b", U)) or (c.get("dosage_form") or "").upper() in (
        "STICK", "CREAM", "GEL", "PASTE", "OINTMENT", "BALM")
    rollon = re.search(r"ROLL[ -]?ON|ROLLER ?BALL", U)
    if not rollon and (SPRAY.search(form) or (claim and not applied)):
        add("spray_powder", [])
        if "talc" in fl:
            add("talc_inhalable", fl["talc"])
    # what the label itself says outside the ingredient list: a named scent ("Fun Melon
    # Fragrance") is a fragrance; an "Allergens: soybeans (glycerin)" statement is that allergen
    for sc in (lc or {}).get("scent_claims") or []:
        if not any(f in fl for f in ("fragrance", "essential_oil")) and not (c.get("product_count") or 1) > 1:
            # quote the scent only when it reads as one ("Fun Melon"), not as list words
            inci = re.search(r"(?i)ATE\b|ENE\b|OL\b|ICONE|ACID|EXTRACT|WAX|GLYCOL|SALICYLATE|SUNSCREEN|SPRAY|"
                             r"INGREDIENT|ANALYTIC|SOLUTION|\bMEN\b|\bTHE\b|DERMATOLOG|RECOMMENDED|ESSENTIAL|ARTIFICIAL", sc)
            add("fragrance", ["a fragrance named on the label" if inci else f"\u201c{sc} fragrance\u201d on the label"], raw=True)
    st = ((lc or {}).get("allergen_statement") or "").upper()
    for g, rx in (("soy", r"\bSOY"), ("milk", r"\bMILK\b"), ("wheat", r"\bWHEAT|\bGLUTEN"), ("tree_nut", r"\bTREE NUTS?\b|\bALMOND|\bMACADAMIA|\bCASHEW|\bWALNUT"),
                  ("peanut", r"\bPEANUT"), ("sesame", r"\bSESAME"), ("egg", r"\bEGGS?\b"),
                  ("fish_shellfish", r"\bFISH\b|\bSHELLFISH|\bCRUSTACEAN")):
        if st and re.search(rx, st) and g not in fl:
            add(g, [f"the label's allergen statement: \u201c{lc['allergen_statement'][:80]}\u201d"], raw=True)
    # a fragrance-free claim on one product of a multi-product filing says nothing of the others
    if lc and lc.get("fragrance_free_claim") and any(f in fl for f in ("fragrance", "essential_oil")) and not (
            int(c.get("product_count") or 1) > 1 or len([x for x in lc.get("spfs") or [] if x > 15]) >= 2):
        add("fragrance_free_conflict", list(fl.get("fragrance") or fl.get("essential_oil") or []))
    _spf = c.get("spf") or (lc or {}).get("spf")
    if _spf and _spf < 15:
        # SPF 2-14: not shown to lower skin cancer risk, whatever else the label claims
        add("not_broad_spectrum", [])
    if lc and lc.get("aging_alert") and not lc.get("broad_spectrum"):
        # the FDA Skin Cancer/Skin Aging Alert is printed only by sunscreens that are not
        # broad spectrum (or are SPF 2-14): 21 CFR 201.327(d)
        add("not_broad_spectrum", [])
    wr = (c.get("label_flags") or {}).get("water_resistant_minutes")
    if wr or WATER_RES.search(form) or (lc and lc.get("water_resistant_minutes")):
        add("water_resistant", [])
    if no_preservative(list(dict.fromkeys(shown + struct))) and not (thin and treason != "short_list"):
        add("no_preservative_water_base", [])
    order = list(meta)
    return [[f, fl[f], meta.get(f, {}).get("l", f)] for f in sorted(fl, key=lambda f: order.index(f) if f in order else 999)]


# ---------------------------------------------------------------- build
BABY_DECISIONS = os.path.join(ROOT, "claims/baby_decisions.csv")


def baby_decisions():
    """The reviewed baby/kids decisions (claims/baby_decisions.csv, kept by
    scripts/baby_track.py and the hand reviews). The evidence pages count this
    population, so the site's baby/kids list and the evidence use the same one."""
    import csv
    if not os.path.exists(BABY_DECISIONS):
        return {}
    return {r["setid"]: r for r in csv.DictReader(open(BABY_DECISIONS, encoding="utf-8"))}


def baby_kids_final(c, dec):
    """Reviewed decision first; the rule only for labels nobody has decided yet."""
    d = dec.get(c["setid"])
    if d and d["decision"] in ("include", "exclude"):
        return d["decision"] == "include", f"reviewed: {d['reason']}"[:200]
    yes, basis = baby_kids(c)
    return yes, (f"rule_unreviewed: {basis}" if yes else None)


HISTORY = os.path.join(ROOT, "data/history/us_formulation_history.jsonl")
STATE = os.path.join(ROOT, "data/history/_state.json")


def delisted_records(live):
    """Canonical-shaped records for labels the snapshot logged as delisted and that
    are not back on DailyMed: label fields from the snapshot state, formula from the
    last history entry that carried one."""
    from classify import classify
    if not (os.path.exists(HISTORY) and os.path.exists(STATE)):
        return {}
    state = json.load(open(STATE, encoding="utf-8"))["setids"]
    last, when = {}, {}
    for line in open(HISTORY, encoding="utf-8"):
        h = json.loads(line)
        if h["setid"] in live:
            continue
        if h["change"] == "delisted":
            when[h["setid"]] = h["observed_on"]
        elif h.get("active_ingredients"):
            last[h["setid"]] = h
    out = {}
    for sid, d in when.items():
        st, h = state.get(sid) or {}, last.get(sid)
        if not h:
            continue
        meta = st.get("meta") or {}
        c = {"setid": sid, "title": meta.get("title") or h.get("product_name"),
             "product_name": meta.get("product_name") or h.get("product_name"),
             "dosage_form": meta.get("dosage_form") or h.get("dosage_form"),
             "labeler": meta.get("labeler") or (re.search(r"\[([^\]]*)\]\s*$", meta.get("title") or "") or [None, None])[1],
             "spf": h.get("spf"), "active_ingredients": h["active_ingredients"],
             "inactive_ingredients": h.get("inactive_ingredients") or [], "first_seen": st.get("first_seen"),
             "last_seen": st.get("last_seen"), "formulation_hash": st.get("formulation_hash"),
             "dailymed_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={sid}", "_delisted_on": d}
        c.update(classify(c))
        out[sid] = c
    return out


RECALL_REVIEWS = os.path.join(ROOT, "data/reference/recall_reviews.json")


def recall_reviews():
    if not os.path.exists(RECALL_REVIEWS):
        return {}
    return json.load(open(RECALL_REVIEWS, encoding="utf-8"))["labels"]


def apply_recall_reviews(sid, recs, reviews):
    """A brand+name match (needs_review) that a person checked against the recall's
    product description becomes `matched` (same product) or is dropped (another product)."""
    rv = reviews.get(sid) or {}
    out = []
    for x in recs:
        v = rv.get(x.get("recall_number"))
        if x.get("status") == "needs_review" and v:
            if v["verdict"] != "same_product":
                continue
            x = dict(x, status="matched", matched_on="reviewed: " + v["why"][:200])
        out.append(x)
    return out


_STEREO = re.compile(r"^\((?:\+/-|\+|-|R|S|Z|E|RS|\d)\)-?$")
_CODE = re.compile(r"^[A-Z]\d{3,}[A-Z]?$")
_CJK = re.compile(r"[\u3131-\uD7A3\u4E00-\u9FFF\u3040-\u30FF]")


_NOTE = re.compile(r"\s*(?:\*+\s*=?\s*(?:certified\s+)?organic(?:\s+ingredients?)?|(?:certified\s+)?organic\s+ingredients?(?:\s*unless\s+otherwise\s+specified)?"
                   r"|unless\s+otherwise\s+specified|may\s+contain(?:\s+one\s+or\s+more\s+of\s+(?:these|the\s+following)\s+ingredients)?\s*:?"
                   r"|\(?\+/-\)?\s*:?\s*$|^with\s+1%\s+or\s+less\s+concentration\s*:|[|]|\s*º\s*organic)", re.I)


def tidy_inactives(items):
    """Repair list-splitting leftovers in a printed list (2026-10-20 audit, 41 labels):
    a lone ',' or '(' ; a stereo qualifier split off its ingredient ('(+/-)-');
    a formula code ('S014'); a footnote marker ('(2)'); 'C12-15' + 'Alkyl Benzoate';
    'Panthenol (Vit' + 'B5)' (a parenthesis split open); OCR 'C1 77491' for CI.
    Returns (list, changed)."""
    out, i, changed = [], 0, False
    items = list(items or [])
    while i < len(items):
        x = items[i].strip()
        nxt = items[i + 1].strip() if i + 1 < len(items) else ""
        if not re.sub(r"[^\w]", "", x) or _STEREO.match(x) or _CODE.match(x):
            changed = True
            i += 1
            continue
        if x.startswith(")"):
            x, changed = x.lstrip(") ").strip(), True
        if re.fullmatch(r"[Cc]\d{1,2}(?:-\d{1,2})?", x) and nxt and nxt[0].isalpha():
            x, i, changed = f"{x.upper()} {nxt}", i + 1, True
        elif re.fullmatch(r"[Cc]\d{1,2}", x) and re.match(r"\d{1,2}\s+\w", nxt):
            x, i, changed = f"{x.upper()}-{nxt}", i + 1, True
        if x.count("(") > x.count(")"):
            # rejoin only when the next 1-3 short pieces close the parenthesis; a label
            # that simply forgot its ')' is left exactly as printed
            y, j = x, i
            while y.count("(") > y.count(")") and j + 1 < len(items) and j - i < 3 and len(items[j + 1]) <= 12:
                frag = items[j + 1].strip()
                y = y + (" " if re.search(r"\bVit\.?$", y, re.I) else ", ") + frag
                j += 1
            if y.count("(") == y.count(")") and j > i:
                x, i, changed = y, j, True
        if x.count("(") > x.count(")") and ", " in x:
            # a label that forgot its ')' glued the next ingredients on: close it after the
            # CI numbers and give the rest back as their own items
            parts = x.split(", ")
            head, k = parts[0], 1
            while k < len(parts) and re.match(r"(?:CI|ci|C\.I\.)\s?\d{5}", parts[k]):
                head, k = head + ", " + parts[k], k + 1
            head += ")" * (head.count("(") - head.count(")"))
            rest = [q for q in parts[k:] if q and not re.fullmatch(r"[A-Z]{2}\d+[A-Z]+\d+", q)]
            out.append(head)
            out.extend(rest)
            changed = True
            i += 1
            continue
        # "(St" + "Paul's Wort) Extract", "Lecithin (Syn" + ...: a parenthesis opened on a
        # short abbreviation that the list split at its full stop
        if re.search(r"\((?:St|Syn|Vit|Ext|Org)\.?$", x, re.I) and nxt and nxt.count(")") > nxt.count("("):
            x, i, changed = x.rstrip(".") + ". " + nxt, i + 1, True
        # footnotes, notes and headers glued onto a name
        y = _NOTE.sub("", x).strip(" .,;|*º°†‡")
        if y != x:
            x, changed = y, True
            if not re.sub(r"[^\w]", "", x):
                i += 1
                continue
        if x == "I" and nxt.lower().startswith("hexanedio"):
            changed = True
            i += 1
            continue
        if re.fullmatch(r"(?:1,2-)?HexanedioI", x):
            x, changed = "1,2-Hexanediol", True
        if "[?" in x or x.endswith("[") :
            x, changed = x.replace("[?", "").rstrip("[ ").strip(), True
        if re.match(r"^C1 \d{5}", x):
            x, changed = "CI " + x[3:], True
        out.append(x)
        i += 1
    return out, changed


SYNONYMS = os.path.join(ROOT, "data/reference/inactive_synonyms.json")


def synonym_map():
    if not os.path.exists(SYNONYMS):
        return {}
    out = collections.defaultdict(set)
    for k in json.load(open(SYNONYMS, encoding="utf-8"))["pairs"]:
        pk, u = k.rsplit("|", 1)
        out[pk].add(u)
    return out


def drop_filed_synonyms(shown, printed_n, c, syn):
    """A filed-only item whose UNII is a known other name of a printed item on the
    same label is the same ingredient: it is not shown twice (scripts/synonyms.py)."""
    if not printed_n or not syn:
        return shown, 0
    import synonyms as Y
    printed, extras = shown[:printed_n], shown[printed_n:]
    uni = {(i.get("name") or "").upper(): i.get("unii") for i in c.get("inactive_ingredients") or []
           if isinstance(i, dict)}
    keep, dropped = [], 0
    for e in extras:
        u = uni.get(e.upper())
        if u and any(u in syn.get(key(p), ()) and Y.related(p, e) for p in printed):
            dropped += 1
            continue
        keep.append(e)
    return printed + keep, dropped


def corrections():
    """Reviewed corrections: labels whose SPL active table contradicts their own
    printed Drug Facts (each entry carries its evidence). Same file the evidence
    pages use, so the site and the evidence count the same actives."""
    return {c["setid"]: c for c in jl(CORRECTIONS)} if os.path.exists(CORRECTIONS) else {}


def scope_overrides():
    """Reviewed scope decisions for labels the classifier gets wrong
    (data/reference/scope_overrides.json: setid -> {in_scope, reason, why})."""
    if not os.path.exists(SCOPE_OVERRIDES):
        return {}
    return json.load(open(SCOPE_OVERRIDES, encoding="utf-8"))["labels"]


_TITLE_ACTS = re.compile(r"\(([^()]*(?:OXIDE|BENZONE|SALATE|OCTINOXATE|CRYLENE|ENSULIZOLE|MERADIMATE)[^()]*)\)", re.I)


def title_actives(c):
    """Last resort when no read of the label ever gave its actives: DailyMed titles
    name them in brackets ('... SPF 20 (AVOBENZONE, HOMOSALATE, OCTISALATE) CREAM').
    Names only, no percentages."""
    m = _TITLE_ACTS.search(c.get("title") or "")
    if not m:
        return []
    parts = re.split(r",|\bAND\b", m.group(1), flags=re.I)
    return [{"name": p.strip().upper(), "unii": None, "percent_ww": None, "percent_basis": "title"}
            for p in parts if p.strip()]


_LT = None


def drop_repeated_extras(shown, printed_n):
    """A filed extra already named earlier in the list ("TOCOPHEROL" after printed
    "Tocopherol", the same filed substance listed for two parts of a kit) is shown once.
    The printed list itself is never changed: a label may print a name twice."""
    out, seen, n = list(shown[:printed_n]), {key(x) or x.upper() for x in shown[:printed_n]}, 0
    for x in shown[printed_n:]:
        k = key(x) or x.upper()
        if k in seen:
            n += 1
            continue
        seen.add(k)
        out.append(x)
    return out, n


def label_text_fragrance(sid, shown):
    """Fragrance the label prints that the parsed list lost: glued to the next
    sentence ('CITRIC ACID, FRAGRANCEPRODUCT FORMULATED ...') or in a footnote
    under an image-transcribed list ('*Fragrance (Parfum)'). Uses the evidence
    pages' label-text reader, so both read the label the same way."""
    global _LT
    if _LT is None:
        sys.path.insert(0, os.path.join(ROOT, "claims"))
        import registry_stats as RS
        _LT = RS
    if any(_LT.FRAGRANCE.search(x.upper()) for x in shown):
        return None
    sec = _LT.printed_section(sid)
    text = sec + " | " + _LT._FOOT.get(sid, "")
    m = _LT.FRAGRANCE.search(text)
    if not m:
        return None
    return "Fragrance (Parfum)" if "PARFUM" in text else "Fragrance"


def build(run_date):
    canon = jl(CANON)
    fixes = corrections()
    syn = synonym_map()
    rreviews = recall_reviews()
    bdec = baby_decisions()
    overrides = scope_overrides()
    from classify import classify
    union = {r["setid"]: r for r in jl(UNION)}
    led = L.load()
    recalls = RecallIndex(jl(RECALLS))
    legacy = json.load(open(REF_PRODUCTS, encoding="utf-8")) if os.path.exists(REF_PRODUCTS) else {}
    prev = {r["setid"]: r for r in jl(MASTER)}
    eng, meta = engine_from_reference()
    out = {}
    # labels that left DailyMed since tracking began (history `delisted`): rebuilt from
    # their last full read so they keep actives, inactives, flags and filter type
    gone = delisted_records({c["setid"] for c in canon})
    for c in canon + list(gone.values()):
        sid = c["setid"]
        if sid in fixes:
            c = dict(c)
            c.update(fixes[sid]["use"])
            c.update(classify(c))                 # category, filters, mineral follow the corrected actives
            c["_actives_corrected"] = fixes[sid].get("error", "")[:300]
        elif not c.get("active_ingredients"):
            # no read of this label gave its actives: the v3.1 db's, else the title's names
            z = (legacy.get(sid) or {}).get("z")
            got = ([{"name": a[0].upper(), "unii": None, "percent_ww": a[1], "percent_basis": "v3.1_db"} for a in z]
                   if z else title_actives(c))
            if got:
                c = dict(c, active_ingredients=got)
                c.update(classify(c))
        ver = c.get("spl_version")
        chk = L.current(led, sid, ver) if ver is not None else (
            max((led.get(sid) or {}).values(), key=lambda r: r.get("checked", ""), default=None))
        acts = actives(c, legacy.get(sid))
        # the strengths the label prints (Drug Facts text), where the structured filing gave
        # none or gave a converted / filed-unit number (agrees with the panel read on
        # 15,176 of 15,177 actives where both exist: scripts/printed_strengths.py)
        _pr = PS.read((LABEL_CLAIMS.get(sid) or {}).get("actives_text"), [a["name"] for a in acts])
        if _pr and int(c.get("product_count") or 1) == 1:
            acts = [dict(a, percent=_pr[a["name"]], percent_basis="label_text")
                    if a["name"] in _pr and (a.get("percent") is None or a.get("percent_basis") != "drug_facts_panel")
                    else a for a in acts]
        ft, mp, cp, organic = filter_split(c, acts)
        # strengths that cannot give the printed SPF (all actives together under 5% w/w for
        # SPF 15+): the filing used the wrong unit or scale (e.g. 3 mg per 1 g for 3%), so the
        # percentages are withheld rather than shown wrong
        _spf = c.get("spf") or (LABEL_CLAIMS.get(sid) or {}).get("spf") or title_spf(c.get("title"), c.get("product_name"))
        _pct = [a.get("percent") for a in acts]
        pct_withheld = bool(acts and _spf and _spf >= 15 and None not in _pct and sum(_pct) < 5) or any(
            # no sunscreen active works below 0.5% (9.5 mg filed per 19 g for a printed 9.5%)
            a.get("percent") is not None and 0 < a["percent"] < 0.5 and a["name"] in US_MAX for a in acts) or any(
            a.get("percent") is not None and a["percent"] > US_MAX.get(a["name"], 100) * 1.01 for a in acts)
        # one filing for several products (a kit, a set of scents, a brand's whole line): the
        # filed strengths are of one product or a mix, and a non-sunscreen active (a nasal
        # spray's, an acne serum's) is not this sunscreen's (2026-10-22 label audit)
        n_products = int(c.get("product_count") or 1)
        # one filing whose label text prints two or more different SPFs (not the boilerplate 15)
        # is several products under one listing (Stream2Sea's line, a stick + lip balm set)
        _spfs = [x for x in (LABEL_CLAIMS.get(sid) or {}).get("spfs") or [] if x > 15]
        if n_products == 1 and len(_spfs) >= 2:
            n_products = len(_spfs)
        multi = n_products > 1 or "KIT" in (c.get("dosage_form") or "").upper()
        acts_all = acts      # a kit's other products (an acne gel's salicylic acid) still give their flags
        if multi:
            uv = [a for a in acts if a["name"].upper() not in {x.upper() for x in c.get("non_uv_actives") or []}]
            acts = uv or acts
            pct_withheld = True
        # a strength computed from mass per volume (g per 100 mL) or volume per volume is not the
        # w/w percentage the label prints (13.2 shown for a printed 12%): withheld, not converted
        acts = [dict(a, percent=None, percent_withheld="not_w_w")
                if a.get("percent") is not None and str(a.get("percent_basis")) in NOT_WW else a for a in acts]
        some_withheld = any(a.get("percent_withheld") for a in acts)
        if pct_withheld:
            acts = [dict(a, percent=None) for a in acts]
        if pct_withheld or some_withheld:
            mp = cp = None
            pct_withheld = True
        # a pain-relief cream (trolamine salicylate, menthol...) with no SPF is not a sunscreen
        analgesic = bool(acts) and all(a["name"].upper() in ANALGESIC for a in acts) and not _spf
        # scope: the classifier says sunscreen drug, then scripts/scope_rules.py takes out
        # SPF makeup / lip / diaper products the classifier let through, and lets back in
        # makeup-format products whose name calls them a sunscreen ("Sunscreen Setting Spritz")
        why = S.scope_reason(c.get("title") or c.get("product_name"))
        back_in = c.get("category") == "makeup" and why is None and S.named_sunscreen(c.get("title"))
        if analgesic and why is None:
            why = "topical_analgesic"
        in_scope = (c.get("category") == "sunscreen" or back_in) and why is None
        if in_scope:
            excluded = None
        elif why:
            excluded = why
        elif c.get("product_type") == "unresolved_zinc":
            excluded = "zinc_only_no_sun_claim"     # zinc oxide alone, no SPF or sunscreen wording
        else:
            excluded = EXCLUDED_REASON.get(c.get("category"), c.get("category"))
        ov = overrides.get(sid)
        if ov:
            in_scope, excluded = ov["in_scope"], (None if ov["in_scope"] else ov["reason"])
        name = clean_name((legacy.get(sid) or {}).get("n") or display_name(c))
        u = union.get(sid)
        if u is None and c.get("_delisted_on"):
            filed = [(i.get("name") if isinstance(i, dict) else str(i)) for i in c.get("inactive_ingredients") or []]
            u = {"i_union": filed, "struct": filed, "i_src": "structured", "i_struct_n": len(filed), "i_text_n": 0}
        shown, struct, u2 = inactives(c, u, chk, acts)
        tidied = False
        if shown and sum(bool(_CJK.search(x)) for x in shown) > 0.3 * len(shown):
            shown, tidied = list(struct), True       # a Korean-only reading: the English filed list is shown
        shown, ch = tidy_inactives(shown)
        tidied = tidied or ch
        shown, n_syn = drop_filed_synonyms(shown, (u2 or {}).get("i_text_n") or 0, c, syn)
        shown, n_rep = drop_repeated_extras(shown, (u2 or {}).get("i_text_n") or 0)
        n_syn += n_rep
        # the printed label is what a parent holds: when its list was read (5+ names), names
        # only the FDA filing has (often another variant or an older formula; 2026-10-22 label
        # audit) are not shown and give no flags
        pn = (u2 or {}).get("i_text_n") or 0
        extras_dropped = 0
        if pn >= 5 and len(shown) > pn:
            extras_dropped, shown = len(shown) - pn, shown[:pn]
        flag_struct = [] if pn >= 5 else struct
        twins = source_twins(shown, struct) if pn >= 5 else []
        if pn >= 5:
            # a filed name that is a printed ingredient under its other name ("BUTYLATED
            # HYDROXYTOLUENE" for a printed "BHT", "PHENOXYETHANOL" for a misprinted
            # "Phenixyethanol") still gives its flags, cited by the printed name
            flag_struct = [f for f in struct if f not in shown and any(strict_twin(f, x) for x in shown)]
            # what an ingredient comes from does not depend on its form: a filed "HAMAMELIS
            # VIRGINIANA LEAF" for a printed witch hazel extract is still a plant, a filed
            # "COLLAGEN, SOLUBLE, FISH SKIN" for a printed "Collagen Extract" still fish
            for f in struct:
                if f in shown or f in flag_struct:
                    continue
                x = next((x for x in shown if (same_display(f, x) or same_display(x, f))
                          and not (re.findall(r"\d+", f) and re.findall(r"\d+", x)
                                   and set(re.findall(r"\d+", f)) != set(re.findall(r"\d+", x)))), None)
                if x is not None:
                    twins = twins + [(x, f)]
        fr = label_text_fragrance(sid, shown)
        if fr:
            shown = shown + [fr]
        thin = len(shown) <= THIN_MAX
        treason = thin_reason(u2, chk) if thin else None
        rec = {
            "setid": sid, "spl_version": ver, "status": "active", "first_seen": c.get("first_seen"),
            "last_seen": c.get("last_seen"), "in_scope": in_scope,
            "excluded_reason": excluded,
            "category": c.get("category"), "name": name, "title": c.get("title"),
            "brand": (legacy.get(sid) or {}).get("b") or c.get("labeler"), "labeler": c.get("labeler"),
            "spf": c.get("spf") or (LABEL_CLAIMS.get(sid) or {}).get("spf") or title_spf(name, c.get("title")),
            "dosage_form": c.get("dosage_form"), "ndc_product": c.get("ndc_product"),
            "broad_spectrum": (None if sid not in LABEL_CLAIMS else
                               # both on one label (a kit, or a label error): unknown
                               None if LABEL_CLAIMS[sid].get("aging_alert") and LABEL_CLAIMS[sid].get("broad_spectrum") else
                               False if LABEL_CLAIMS[sid].get("aging_alert") else
                               True if LABEL_CLAIMS[sid].get("broad_spectrum") else None),
            "dailymed_url": c.get("dailymed_url"), "effective_date": c.get("effective_date"),
            "actives": acts,
            # why strengths are not shown: several products in one filing, a filed amount that is
            # not w/w, or filed strengths that cannot give the printed SPF
            "actives_percent_withheld": ("multi_product" if multi else "not_w_w" if some_withheld
                                         else "implausible" if pct_withheld else None),
            "mineral_type": mineral_type(acts), "filter_type": ft,
            "mineral_pct": mp, "chemical_pct": cp,
            "is_mineral": ft not in ("chemical_only", "no_uv_filter"),
            "is_baby_kids": baby_kids_final(c, bdec)[0], "baby_kids_basis": baby_kids_final(c, bdec)[1],
            "inactives": shown, "inactive_source": (u2 or {}).get("i_src", "structured"),
            "inactives_filed_n": (u2 or {}).get("i_struct_n", 0), "inactives_printed_n": (u2 or {}).get("i_text_n", 0),
            "label_check": (chk or {}).get("status"), "label_check_date": (chk or {}).get("checked"),
            "label_check_stale": bool(L.stale(led, sid, ver)) and chk is None,
            "thin": thin, "thin_reason": treason,
            "flags": flags(eng, meta, shown, flag_struct, acts_all if multi else acts, organic, c, thin, treason, twins),
            "filed_extras_dropped": extras_dropped or None,
            "multi_product": (n_products if n_products > 1 else "kit") if multi else None,
            "recalls": recalls.match(c, c.get("product_name") or name) if recalls.all else [],
            "recall_checked": bool(recalls.all),
            "formulation_hash": c.get("formulation_hash"),
            "fetch_status": c.get("fetch_status"),
        }
        if c.get("_actives_corrected"):
            rec["actives_corrected"] = c["_actives_corrected"]
        if ov:
            rec["scope_override"] = ov["why"]
        if fr:
            rec["inactives_added_from_label_text"] = [fr]
        if tidied:
            rec["inactives_tidied"] = True
        if n_syn:
            rec["filed_synonyms_dropped"] = n_syn
        if not recalls.all and (legacy.get(sid) or {}).get("r"):
            rec["recalls"] = [{"recall_number": None, "status": "matched", "matched_on": "v3.1_db",
                               "hazards": legacy[sid]["r"]}]
        rec["recalls"] = apply_recall_reviews(sid, rec["recalls"], rreviews)
        if sid in gone:
            rec.update(status="discontinued", discontinued_on=c["_delisted_on"], last_seen=c.get("last_seen"),
                       note="no longer on FDA DailyMed; last full read kept")
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
