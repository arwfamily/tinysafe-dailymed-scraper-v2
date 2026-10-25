#!/usr/bin/env python3
"""Rebuild the Sunnytime / TinySafe sunscreen DB (db.json) with full inactive lists.

The v3.1 db.json (2026-09-28) read only each label's structured SPL ingredient
table. Many labelers fill that table with a few inactives and print the full
list in the Drug Facts text, so flags were missed. This script:

  1. takes every product of the v3.1 db.json (same 6,544 labels, same actives,
     names, brands, SPF, recall links);
  2. replaces its inactive list with structured ∪ printed Drug Facts list
     (data/views/inactive_union.jsonl, built by scripts/inactive_union.py);
  3. recomputes the inactive-ingredient flags with rules v3.2
     (scripts/sunnytime_rules.py); flags v3.1 derived from actives or from the
     product form are kept as they were;
  4. records per product: i_src, i_struct_n, i_text_n, thin, thin_reason.

It also writes a report comparing three states, so each change can be traced:
  S0 = v3.1 as published, S1 = v3.2 rules on the v3.1 (structured) lists,
  S2 = v3.2 rules on the union lists (the new db.json).

Usage:
  python3 scripts/sunnytime_db.py OLD_DB NEW_DB [REPORT.json]
  python3 scripts/sunnytime_db.py --check-rules OLD_DB
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sunnytime_rules as R  # noqa: E402
from inactive_union import key  # noqa: E402

UNION = os.path.join(ROOT, "data/views/inactive_union.jsonl")
# Labels re-checked on DailyMed (SPL text and label images read twice independently)
THIN_CHECK = os.path.join(ROOT, "data/corrections/thin_check_2026-10-19.jsonl")
# every label re-read on DailyMed (current SPL text; label images where the SPL has no text)
FULL_CHECK = os.path.join(ROOT, "data/corrections/full_check_2026-10-19.jsonl")
FULL = {}
FULL_USE = {"confirmed", "partial", "text_confirms_current", "no_list_on_label_images", "image_unreadable",
            "label_image_mismatch", "spl_not_on_dailymed", "non_english_label"}
PRODUCT_LEVEL = {"spray_powder", "water_resistant", "talc_inhalable", "no_preservative_water_base"}
THIN_MAX = 7
EVIDENCE_CAP = 4                       # v3.1 kept at most 4 names per flag
RULES_VERSION = "v3.2 · 2026-10-19"
THIN = {}
_EXTRA_WORDS = re.compile(r"\b(EXTRACT|FILTRATE|FERMENT FILTRATE|POWDER)\b")


def strong_key(name):
    """key() with bracketed common names and 'extract' dropped, so INCI
    'Calendula Officinalis Flower Extract' meets SRS 'CALENDULA OFFICINALIS FLOWER'."""
    u = re.sub(r"\(.*?\)", " ", (name or "").upper())
    u = _EXTRA_WORDS.sub(" ", u)
    return key(u)


class Engine:
    def __init__(self, db):
        self.names = db["names"]
        self.v31 = collections.defaultdict(set)          # name -> flags v3.1 gave it
        for p in db["p"]:
            for f in p["v3"]:
                for x in f[1]:
                    self.v31[x].add(f[0])
        self.known = set(self.names)
        freq = collections.Counter(self.names[i] for p in db["p"] for i in p["i"])
        self.by_strong = {}
        for n in sorted(self.known, key=lambda n: (not self.v31.get(n), -freq[n])):
            self.by_strong.setdefault(strong_key(n), n)
        self.genera = set()
        for n, fs in self.v31.items():
            if "botanical_count" in fs:
                w = re.findall(r"[A-Z]+", re.sub(r"\(.*?\)", " ", n.upper()))
                if w:
                    self.genera.add(w[0])
        self.plants = R.PlantIndex(self.v31)
        self.corrections = collections.Counter()
        self._cache = {}

    def v31_flags(self, name):
        return set(self.v31.get(name, set()))

    def flags(self, name):
        """(flags, how) for one inactive ingredient name under rules v3.2."""
        if name in self._cache:
            return self._cache[name]
        if name in self.known:
            fs, how = self.v31_flags(name), "v3.1 name"
            fs |= R.pattern_flags(name, self.genera) & (R.ADDITIVE | R.FAMILY_ADDITIVE)
            fs |= R.dict_gaps(name)
        else:
            twin = self.by_strong.get(strong_key(name))
            if twin is not None:
                fs, how = self.v31_flags(twin), "same name as v3.1 '" + twin + "'"
                fs |= R.pattern_flags(name, self.genera) & (R.ADDITIVE | R.FAMILY_ADDITIVE)
                fs |= R.dict_gaps(name)
            else:
                fs = R.pattern_flags(name, self.genera) | self.plants.flags(name) | R.dict_gaps(name)
                how = "pattern"
        for f in list(fs):
            if (name, f) in R.V32_NOT or (how.startswith("same") and (twin, f) in R.V32_NOT):
                fs.discard(f)
        # an essential oil is an oil: an extract, a flower water (hydrosol) or a resin is not one,
        # whatever v3.1 decided for the name (rules v3.3)
        if "essential_oil" in fs and not re.search(r"\bOIL\b|\bOLEUM\b", name.upper()):
            fs.discard("essential_oil")
        # a seed, kernel or nut oil is a fixed oil (chia, sunflower), not an essential oil,
        # whatever name v3.1 matched it to (2026-10-22 audit: Salvia hispanica seed oil)
        if "essential_oil" in fs and re.search(r"\b(SEED|KERNEL|NUT|BRAN|GERM)\b.*\bOIL\b", name.upper()) \
                and not re.search(r"CARROT|DAUCUS|CORIAND", name.upper()):
            fs.discard("essential_oil")
        # propylene glycol itself, not an ester of it (propylene glycol dicaprylate/dicaprate)
        if "propylene_glycol" in fs and R.PG_ESTER.search(name.upper()):
            fs.discard("propylene_glycol")
        fs.discard("chemical_filter_active")             # actives only
        # Gardenia jasminoides (cape jasmine) is not jasmine and not an EU-listed allergen, whatever
        # v3.1 decided for the name (2026-10-24 third audit, Rare Beauty)
        # "sr-" names are synthetic recombinant proteins (Pacifica's vegan collagen, Sr-Hydrozoan
        # Polypeptide-1): not taken from an animal (2026-10-24 post-fix audit)
        # a PEG/PPG derivative of a plant oil (PEG-40 hydrogenated castor oil) is a synthetic
        # emulsifier, not a plant extract (2026-10-24 audits)
        if "botanical_count" in fs and re.match(r"\s*(PEG|PPG)[- ]?\d", name.upper()):
            fs.discard("botanical_count")
        # 2026-10-24 independent audit: a PPG (propoxylated) name is not ethoxylated; 4-methyl-
        # benzylidene camphor (also misprinted "benzylidence") is a UV filter, not camphor; sacha
        # inchi ("mountain peanut", Plukenetia) is not peanut
        _U = name.upper()
        if "ethoxylated" in fs and re.search(r"\bPPG", _U) and "PEG" not in _U and not R.RX["ethoxylated"].search(
                re.sub(r"\bPPG[- ]?\d*", " ", _U)):
            fs.discard("ethoxylated")
        if "eu_fragrance_allergen" in fs and re.search(r"BENZYLIDENC?E\s+CAMPHOR", _U) and not R.RX[
                "eu_fragrance_allergen"].search(re.sub(r"\S*BENZYLIDENC?E\s+CAMPHOR", " ", _U)):
            fs.discard("eu_fragrance_allergen")
        if re.search(r"BENZYLIDENCE\s+CAMPHOR", _U):
            fs.add("hidden_uv_booster")
        if "peanut" in fs and re.search(r"MOUNTAIN PEANUT|PLUKENETIA|SACHA INCHI", _U) and not re.search(
                r"ARACHIS|(?<!MOUNTAIN )PEANUT", _U):
            fs.discard("peanut")
        if "animal_derived" in fs and re.match(r"\s*SR[- ]", name.upper()):
            fs.discard("animal_derived")
        if "eu_fragrance_allergen" in fs and "JASMINOIDES" in name.upper() and not R.RX["eu_fragrance_allergen"].search(
                name.upper().replace("JASMINOIDES", "")):
            fs.discard("eu_fragrance_allergen")
        # "Synthetic Beeswax", "Synthetic Wax": made in a lab, not from bees or animals
        if R.SYNTHETIC.search(name.upper()):
            fs -= R.SOURCE_FLAGS
        self._cache[name] = (fs, how)
        return fs, how


def no_preservative(names):
    u = [n.upper() for n in names]
    # water-based: water is one of the main ingredients (lists run from most to least), not
    # a trace at the end of an oil (2026-10-22 audit: a body oil with water listed last)
    head = u[:max(3, len(u) // 3)]
    return any(R.WATER.search(x) for x in head) and not any(R.PRESERVATIVE.search(x) for x in u)


def thin_reason(u):
    """Why a list is short: the label's printed list could not be read, the
    label itself prints almost nothing (e.g. only 'Water'), or the printed list
    was read and is genuinely short (e.g. a balm)."""
    if not u or u["i_text_n"] == 0:
        return "no_printed_list"
    names = u["i_union"]
    if u["i_union_n"] <= 3 and any(R.WATER.search(x.upper()) for x in names):
        return "label_prints_too_little"
    return "short_list"


def inactive_flags(engine, names):
    out = collections.defaultdict(list)
    for n in names:
        fs, _ = engine.flags(n)
        for f in fs:
            out[f].append(n)
    return out


def tally(products, flagkey="v3"):
    c = collections.Counter()
    for p in products:
        for f in {x[0] for x in p[flagkey]}:
            c[f] += 1
    return c


def _akeys(p, u):
    """Keys of the product's declared actives (db z list, plus the union row's)."""
    from inactive_union import _ACTIVE_SYN
    ks = set()
    for z in p.get("z") or []:
        k = key(z[0]); ks.add(k); ks |= _ACTIVE_SYN.get(k, set())
    return ks


def build(db, union):
    eng = Engine(db)
    names = list(db["names"])
    idx = {n: i for i, n in enumerate(names)}
    meta = db["meta"]
    out, s1 = [], []
    for p in db["p"]:
        old_names = [db["names"][i] for i in p["i"]]
        old = {f[0]: f for f in p["v3"]}
        # flags v3.1 drew from actives or from the product, not from inactives
        from_inactives = set()
        for n in old_names:
            from_inactives |= eng.v31_flags(n)
        keep = {f: v for f, v in old.items()
                if f in PRODUCT_LEVEL - {"no_preservative_water_base"} or f not in from_inactives
                or any(x not in old_names for x in v[1])}
        keep.pop("no_preservative_water_base", None)

        def flags_for(lst):
            fl = {f: list(v) for f, v in keep.items()}
            for f, ev in inactive_flags(eng, lst).items():
                if f in fl:
                    fl[f] = [fl[f][0], list(dict.fromkeys(fl[f][1] + ev))[:EVIDENCE_CAP], fl[f][2]]
                else:
                    fl[f] = [f, ev[:EVIDENCE_CAP], meta.get(f, {}).get("l", f)]
            if no_preservative(lst):
                fl["no_preservative_water_base"] = ["no_preservative_water_base", [],
                                                    meta["no_preservative_water_base"]["l"]]
            order = list(meta)
            return [fl[f] for f in sorted(fl, key=lambda f: order.index(f) if f in order else 999)]

        s1.append({"id": p["id"], "v3": flags_for(old_names)})
        u = union.get(p["id"])
        chk = THIN.get(p["id"])
        full = FULL.get(p["id"])
        if full and full["status"] in FULL_USE and (not chk or chk["status"] not in ("confirmed", "partial")
                                                    or full["status"] in ("confirmed", "partial") and "two_reads" in full.get("source", "")
                                                    and chk.get("source") == "label_text"):
            chk = FULL[p["id"]]
        if u and chk and chk.get("inactives") and chk["status"] in ("confirmed", "partial"):
            from inactive_union import same as _same
            printed = list(chk["inactives"])
            from inactive_union import same_display as _sd
            extra = [x for x in u["struct"] if not any(_sd(x, t) for t in printed) and len(x.split()) <= 12]
            u = dict(u, i_union=printed + extra, i_text_n=len(printed),
                     i_src="image" if "image" in chk["source"] else "both")
        from inactive_union import is_active
        ak = _akeys(p, u)
        new_names = [n for n in (u["i_union"] if u else old_names) if not is_active(n, ak)]
        struct_names = [n for n in (u["struct"] if u else []) if not is_active(n, ak)]
        for n in new_names:
            if n not in idx:
                idx[n] = len(names)
                names.append(n)
        q = dict(p)
        q["i"] = [idx[n] for n in new_names]
        # flags read every structured name too: the filing's name can be more
        # specific than the printed one ("LECITHIN, SOYBEAN" vs "Lecithin")
        q["v3"] = flags_for(list(dict.fromkeys(new_names + struct_names)))
        if u:
            q.update({"i_src": u["i_src"], "i_struct_n": u["i_struct_n"], "i_text_n": u["i_text_n"]})
        else:
            q.update({"i_src": "structured", "i_struct_n": len(old_names), "i_text_n": 0})
        n_i = len(q["i"])
        q["thin"] = n_i <= THIN_MAX
        if q["thin"]:
            q["thin_reason"] = thin_reason(u) if u else "no_printed_list"
            st = (chk or {}).get("status")
            if st == "no_list_on_label_images":
                q["thin_reason"] = "no_printed_list"          # checked: no list in the text or the images
            elif st == "image_unreadable":
                q["thin_reason"] = "label_image_unreadable"
            if q["thin_reason"] != "short_list":
                # too little on the label to say a preservative is missing
                q["v3"] = [f for f in q["v3"] if f[0] != "no_preservative_water_base"]
        if chk:
            q["label_check"] = chk["status"]
        if u and u.get("text_unreadable"):
            q["text_unreadable"] = True
        out.append(q)
    new = dict(db)
    new["names"] = names
    new["p"] = out
    new["rules_version"] = RULES_VERSION
    new["inactives_as_of"] = "2026-10-19"
    new["inactives_note"] = ("Inactive ingredients = the label's structured SPL table plus the printed Drug Facts "
                             "'Inactive ingredients' list (union). thin = 7 or fewer inactives; thin_reason: "
                             "no_printed_list | label_prints_too_little | label_image_unreadable | short_list. "
                             "label_check: result of reading the label on DailyMed (text and images, twice).")
    return new, s1, eng


BABY = re.compile(r"\b(BABY|BABIES|KIDS?|CHILD(REN)?|TODDLERS?|INFANTS?|LITTLE ONES|JUNIOR|PEDIATRIC)\b", re.I)


def report(old, new, s1, eng):
    s0c, s1c, s2c = tally(old["p"]), tally(s1), tally(new["p"])
    flags = sorted(set(s0c) | set(s1c) | set(s2c), key=lambda f: -s2c[f])
    old_short = sum(1 for p in old["p"] if len(p["i"]) <= THIN_MAX)
    new_short = sum(1 for p in new["p"] if p["thin"])
    tr = collections.Counter(p.get("thin_reason") for p in new["p"] if p["thin"])
    src = collections.Counter(p["i_src"] for p in new["p"])

    def mineral(p):
        return p["m"] in ("zinc", "titanium", "zinc_titanium") and not any(f[0] == "chemical_filter_active" for f in p["v3"])

    def lipids(p, names):
        ins = [names[i].upper() for i in p["i"]]
        cer = any("CERAMIDE" in x for x in ins)
        chol = any(re.search(r"\bCHOLESTEROL\b", x) for x in ins)
        fa = any(re.search(r"\b(STEARIC|PALMITIC|LINOLEIC|LINOLENIC|OLEIC|BEHENIC|MYRISTIC|LAURIC) ACID\b", x) for x in ins)
        return cer and chol and fa

    def same_formula_groups(db):
        g = collections.defaultdict(set)
        for p in db["p"]:
            if len(p["i"]) < 8:
                continue
            k = (tuple(sorted((z[0], round(z[1] or 0, 2)) for z in p["z"])),
                 tuple(sorted({key(db["names"][i]) for i in p["i"]})))
            g[k].add(p["b"].upper())
        return sum(1 for v in g.values() if len(v) > 1), sum(len(v) for v in g.values() if len(v) > 1)

    baby_old = [p for p in old["p"] if BABY.search(p["n"])]
    baby_new = [p for p in new["p"] if BABY.search(p["n"])]
    rep = {
        "products": len(new["p"]),
        "inactives_7_or_fewer": {"before": old_short, "after": new_short, "thin_reason": dict(tr)},
        "i_src": dict(src),
        "flags": {f: {"S0_v31": s0c[f], "S1_v32_structured": s1c[f], "S2_v32_union": s2c[f]} for f in flags},
        "hidden_uv_booster_mineral_only": {
            "S0": sum(1 for p in old["p"] if mineral(p) and any(f[0] == "hidden_uv_booster" for f in p["v3"])),
            "S2": sum(1 for p in new["p"] if mineral(p) and any(f[0] == "hidden_uv_booster" for f in p["v3"])),
            "mineral_only_products": sum(1 for p in new["p"] if mineral(p))},
        "baby_by_name": {"products": len(baby_new),
                         "all_three_barrier_lipids_before": sum(lipids(p, old["names"]) for p in baby_old),
                         "all_three_barrier_lipids_after": [p["n"] for p in baby_new if lipids(p, new["names"])],
                         "fragrance_before": sum(1 for p in baby_old if any(f[0] == "fragrance" for f in p["v3"])),
                         "fragrance_after": sum(1 for p in baby_new if any(f[0] == "fragrance" for f in p["v3"])),
                         "thin_after": sum(1 for p in baby_new if p["thin"])},
        "same_formula_different_brand": {"groups_before": same_formula_groups(old)[0],
                                         "groups_after": same_formula_groups(new)[0]},
        "v32_corrections_applied": [{"name": n, "flag": f, "reason": r} for (n, f), r in R.V32_NOT.items()],
        "name_resolution": dict(collections.Counter(h.split(" '")[0] for _, h in eng._cache.values())),
    }
    return rep


def check_rules(db):
    """Pattern rules vs v3.1 decisions on the names v3.1 saw."""
    eng = Engine(db)
    seen = {db["names"][i] for p in db["p"] for i in p["i"]}
    for f in sorted({f for fs in eng.v31.values() for f in fs} - PRODUCT_LEVEL - {"chemical_filter_active"}):
        tp = fp = fn = 0
        for n in seen:
            t = f in eng.v31.get(n, set())
            pr = f in (R.pattern_flags(n, eng.genera) | eng.plants.flags(n))
            tp += t and pr
            fp += pr and not t
            fn += t and not pr
        print(f"{f:28s} agree={tp:5d} pattern-only={fp:4d} v3.1-only={fn:4d}")


def main():
    if sys.argv[1:2] == ["--check-rules"]:
        check_rules(json.load(open(sys.argv[2], encoding="utf-8")))
        return
    old_path, new_path = sys.argv[1], sys.argv[2]
    rep_path = sys.argv[3] if len(sys.argv) > 3 else None
    old = json.load(open(old_path, encoding="utf-8"))
    union = {}
    for line in open(UNION, encoding="utf-8"):
        r = json.loads(line)
        union[r["setid"]] = r
    global THIN
    THIN = {}
    if os.path.exists(THIN_CHECK):
        for line in open(THIN_CHECK, encoding="utf-8"):
            r = json.loads(line)
            THIN[r["setid"]] = r
    if os.path.exists(FULL_CHECK):
        for line in open(FULL_CHECK, encoding="utf-8"):
            r = json.loads(line)
            FULL[r["setid"]] = r
    new, s1, eng = build(old, union)
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, separators=(",", ":"))
    rep = report(old, new, s1, eng)
    if rep_path:
        with open(rep_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: rep[k] for k in ("products", "inactives_7_or_fewer", "i_src", "hidden_uv_booster_mineral_only",
                                          "same_formula_different_brand")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
